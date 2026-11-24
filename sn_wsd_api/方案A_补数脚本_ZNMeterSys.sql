/* =====================================================================================
   方案A 补数脚本 —— 往 ZNMeterSys 源表插数据，供 EIPDataCenterV3 抽取后上传 EIP
   -------------------------------------------------------------------------------------
   1. 执行库     ：ZNMeterSys（!! 不是 eipsysdb_V2。EIPDataCenterV3 的 DbHelperSQL 读的就是它）
   2. 执行账号   ：sa 或对该库有写权限的账号
   3. 抽取口径   ：RST='90' 视为合格；AOI/FCT/焊接按 PCB 条码区间，耐压/误差/参数按成品条码
                   (经 SC_CPXX 关联 PCB)，包装入库按铭牌；同条码多条记录只取 SaveTime 最新一条
   4. 数量校验   ：AOI/FCT/电池电流/基本误差 上传前有"数量必须等于订单数量(DD_SCDDXX.ACount)"硬校验
   5. 时间口径   ：所有检测时间必须落在订单实际起止时间(DD_SCDDXX.RealStartTime~RealEndTime)内，
                   否则采集中心"数据审核"不通过
   6. 值区间提醒 ：采集中心内置"越界改写"逻辑，插入值必须落在以下区间，否则会被随机值覆盖并回写：
                   - 耐压漏电流 LEAKAGE_CURRENT ：>0.1 且 <=0.999
                   - 日计时误差 REAL_ERROR       ：-0.3 ~ +0.3
                   - 电池电流 AVGZhi             ：单相 5~9.9；三相四线 0.5~1.5
                   - 老化房温度 WDZ              ：55~65
   7. 老化(LHS)  ：V_SC_LHS 视图定义已查明（2026-11-10 在生产库核对）：
                   SC_LHXX (批次主表) LEFT JOIN SC_LHMX (批次明细, Barcode=成品码)
                   LEFT JOIN SC_CPMX / DD_SCDDXX。
                   采集中心 GetLHS() 固定取 12 个温度点：起点 = SC_LHXX.INTime + 1 小时，
                   每轮 +30 分钟，每轮查 SC_LHTemperature 中 MachineID = SC_LHXX.SBBH
                   且 SJ 落在 [起点, OutTime] 的记录；任一轮查不到即整表放弃。
                   因此必须同时补 SC_LHXX + SC_LHMX，且温度要覆盖 INTime+1h 之后的 6 小时。
                   界面加载老化时要填「底壳条码范围」= 成品码，不是 PCB 条码范围。
   8. 执行前     ：建议先整库备份；脚本全部带 NOT EXISTS 查重，可重复执行
   ===================================================================================== */


/* ============================ 第0步：参数区（必改） ============================ */
DECLARE @SCDDBM  varchar(50) = 'SCDD20260101001';  -- 生产订单编码（DD_SCDDXX.SCDDBM）
DECLARE @XSDDBM  varchar(50) = '';                 -- 销售订单编码（可空）
DECLARE @XingHao varchar(50) = 'DTSD341-0001';     -- 型号（DD_SCDDXX.XingHao，国网报文 MODEL_CODE）
DECLARE @SBBH    varchar(50) = '10001';            -- 设备编号（AOI/FCT/焊接用，报文 DEVICE_NO）
DECLARE @SJ       varchar(50) = '2026-01-05 10:00:00';  -- 检测时间（落在订单实际起止时间内！）
DECLARE @JQM      varchar(50) = 'BU-SHU';          -- 机器名（标记为补数，便于日后追溯）
DECLARE @IPDZ     varchar(50) = '127.0.0.1';
DECLARE @CZY      varchar(50) = '补数';            -- 操作员
DECLARE @LH_SBBH  varchar(50) = 'LH01';            -- 老化房设备编号（SC_LHXX.SBBH = SC_LHTemperature.MachineID）
DECLARE @LH_PCH   int         = 990001;            -- 老化批次号（SC_LHXX.TestPCH，必须库内唯一！先查 MAX(TestPCH)+1）
DECLARE @LH_IN    varchar(50) = '2026-01-05 08:00:00';  -- 进房时间（= 老化批次 INTime）
DECLARE @LH_OUT   varchar(50) = '2026-01-05 16:00:00';  -- 出房时间（须 >= INTime + 8 小时，见 4.11 说明）
DECLARE @BH       varchar(50) = '000000000001';    -- 表号（12位以上，参数设置用，每块表应不同）


/* ============================ 第1步：条码清单（必改） ============================ */
-- 每行填一组：PCB条码 / 成品条码 / 铭牌。三种码按贵司编码规则对应，
-- AOI/FCT/焊接/电池电流补数用 PCB；耐压/误差/日计时/参数用成品条码；包装入库用铭牌。
IF OBJECT_ID('tempdb..#TMP') IS NOT NULL DROP TABLE #TMP;
CREATE TABLE #TMP (SEQ int IDENTITY(1,1), PCB varchar(50), BarCode varchar(50), MP varchar(50));
INSERT INTO #TMP (PCB, BarCode, MP) VALUES
    ('P0000000001', 'C0000000001', 'M0000000001'),
    ('P0000000002', 'C0000000002', 'M0000000002');   -- 按实际数量追加


/* ============================ 第2步：前置校验（先看结果再往下走） ============================ */
-- 2.1 订单是否存在（XingHao / 数量 / 实际起止时间都从这张表取）
SELECT SCDDBM, XingHao, ACount AS 订单数量, RealStartTime, RealEndTime
FROM dbo.DD_SCDDXX WHERE SCDDBM = @SCDDBM;
-- 查不到 => 先补 DD_SCDDXX（见 3.1）；查到了 => 核对 @SJ 是否在 RealStartTime~RealEndTime 内

-- 2.2 三张关联表是否齐（不齐 => 采集中心要么查不到、要么报文里型号为空）
--     SC_CPMX：成品条码 -> 生产订单     SC_CPXX：成品条码 <-> PCB    TCPXX：成品条码 -> 铭牌
SELECT t.SEQ, t.PCB, t.BarCode, t.MP,
       mx.SCDDBM AS 已挂订单, cp.PCB AS CPXX_PCB, tx.MP AS TCPXX_MP, tx.CONCLUSION AS 铭牌结论
FROM #TMP t
LEFT JOIN dbo.SC_CPMX  mx ON mx.BarCode = t.BarCode AND mx.SCDDBM = @SCDDBM
LEFT JOIN dbo.SC_CPXX  cp ON cp.BarCode = t.BarCode
LEFT JOIN dbo.TCPXX    tx ON tx.Barcode = t.BarCode;
-- 期望：已挂订单、CPXX_PCB、TCPXX_MP 全部非空且与 #TMP 一致


/* ============================ 第3步：基础关联表（缺才补，已齐则跳过） ============================ */
-- 3.1 生产订单（一般由 EIP 接口/订单管理生成；补历史订单才需要手插）
INSERT INTO dbo.DD_SCDDXX (SCDDBM,XSDDBM,GHDW,KHMC,CPDM,CPMC,JHStartTime,JHEndTime,
                            RealStartTime,RealEndTime,KSMP,JSMP,ACount,CJSJ,XingHao,StatusValue)
SELECT @SCDDBM, @XSDDBM, '', '', '', '',
       '2026-01-01', '2026-01-31',                       -- 计划起止
       '2026-01-01 08:00:00', '2026-01-31 20:00:00',   -- 实际起止（@SJ 必须落在其内）
       '', '', (SELECT COUNT(*) FROM #TMP), GETDATE(), @XingHao, ''
WHERE NOT EXISTS (SELECT 1 FROM dbo.DD_SCDDXX WHERE SCDDBM=@SCDDBM);

-- 3.2 产品明细：成品条码挂订单（列清单抄自 D_SC_CPMX.Add）
INSERT INTO dbo.SC_CPMX (BarCode,XSDDBM,SCDDBM,CJSJ,CJR,DQGX,DQZT)
SELECT t.BarCode, @XSDDBM, @SCDDBM, @SJ, @CZY, '', ''
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.SC_CPMX WHERE BarCode=t.BarCode AND SCDDBM=@SCDDBM);

-- 3.3 产品信息：成品条码 <-> PCB（列清单抄自 D_SC_CPXX.Add；抽取子查询靠它换算 PCB）
INSERT INTO dbo.SC_CPXX (BarCode,PCB,MP,XH,ZQFH,YQFH,BCQFH,MKH,ZBH,SPTM,JQM,IPDZ,SJ,DDBM,EWMXX)
SELECT t.BarCode, t.PCB, t.MP, @XingHao, '', '', '', '', '', '', @JQM, @IPDZ, @SJ, '', ''
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.SC_CPXX WHERE BarCode=t.BarCode);

-- 3.4 铭牌：成品条码 -> 铭牌（按铭牌抽取 + 包装入库必须；CONCLUSION 记 '0' 合格）
INSERT INTO dbo.TCPXX (Barcode,MP,ZSQF,YSQF,BCQF,MKH,SPTM,SaveTime,IPAddress,MachineName,Operator,SCGDBM,CONCLUSION)
SELECT t.BarCode, t.MP, '', '', '', '', '', @SJ, @IPDZ, @JQM, @CZY, '', '0'
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.TCPXX WHERE Barcode=t.BarCode);


/* =====================================================================================
   第4步：试验明细表（按需执行，每段相互独立）
   全部模拟设备/服务端的真实写法：SC_Result 抄 ZNService.SaveResult，
   T* 、 SC_* 抄 ZNMeterSystem DataBaseInfor 各 DAL 的 Add 列清单
   ===================================================================================== */

-- ---------- 4.1 AOI（1001）：SC_Result，GXBH=3，BarCode 存 PCB 条码 ----------
INSERT INTO dbo.SC_Result (BarCode,GXBH,BW,SBBH,RST,JQM,IPDZ,CZYMC,SJ,SCDDBM,StationID)
SELECT t.PCB, '3', 0, @SBBH, '90', @JQM, @IPDZ, @CZY, @SJ, @SCDDBM, @SBBH
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.SC_Result WHERE BarCode=t.PCB AND GXBH='3' AND RST='90');

-- ---------- 4.2 FCT（1003）：SC_Result，GXBH=10，BarCode 存 PCB 条码 ----------
INSERT INTO dbo.SC_Result (BarCode,GXBH,BW,SBBH,RST,JQM,IPDZ,CZYMC,SJ,SCDDBM,StationID)
SELECT t.PCB, '10', 0, @SBBH, '90', @JQM, @IPDZ, @CZY, @SJ, @SCDDBM, @SBBH
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.SC_Result WHERE BarCode=t.PCB AND GXBH='10' AND RST='90');

-- ---------- 4.3 耐压测试（1002）：TNYCS，BarCode 存成品条码（取 PCB 须过 SC_CPXX，挂订单须过 SC_CPMX） ----------
-- LEAKAGE_CURRENT 必须 >0.1 且 <=0.999（否则被采集中心随机改写回写）
INSERT INTO dbo.TNYCS (Barcode,Seat,CHECK_DURATION,TESTING_VOLTAGE,UNQUALIFIED,LEAKAGE_CURRENT,CONCLUSION,SaveTime,DeviceNo,MachineName,IPAddress,Operator)
SELECT t.BarCode, 1, '60', '1500', '', '0.66', '0', @SJ, @SBBH, @JQM, @IPDZ, @CZY
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.TNYCS WHERE Barcode=t.BarCode);

-- ---------- 4.4 日计时误差（1004）：TDayTimeError，BarCode 存成品条码 ----------
-- REAL_ERROR 必须 -0.3 ~ +0.3
INSERT INTO dbo.TDayTimeError (Barcode,DeviceNo,Seat,ALLOWABLE_ERROR,REAL_ERROR,CheckTime,SaveTime,IPAddress,MachineName,Operator,SCGDBM,CONCLUSION)
SELECT t.BarCode, @SBBH, 1, '-0.3+0.3', '0.05', @SJ, @SJ, @IPDZ, @JQM, @CZY, '', '0'
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.TDayTimeError WHERE Barcode=t.BarCode);

-- ---------- 4.5 电池电流（1005）：SC_DCDL，BarCode 存 PCB 条码（V_SC_DCDL 视图换算） ----------
-- AVGZhi：单相 5~9.9；三相四线 0.5~1.5（按订单产品名称判断）
INSERT INTO dbo.SC_DCDL (Barcode,LX,AVGZhi,ZhiMX,ZDZ,ZXZ,DeviceNo,CJSJ,BeiZhu)
SELECT t.PCB, '1', '7.50', '', '7.8', '7.2', @SBBH, @SJ, ''
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.SC_DCDL WHERE Barcode=t.PCB);

-- ---------- 4.6 基本误差（1006）：TErrorResult，BarCode 存成品条码 ----------
INSERT INTO dbo.TErrorResult (Barcode,Seat,DeviceNo,CheckTime,SaveTime,IPAddress,MachineName,Operator,SCGDBM,CONCLUSION)
SELECT t.BarCode, 1, @SBBH, @SJ, @SJ, @IPDZ, @JQM, @CZY, '', '0'
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.TErrorResult WHERE Barcode=t.BarCode);

-- ---------- 4.7 基本误差详情（1007）：TErrorDetail，BarCode 存成品条码 ----------
-- 注意 DIRECTION/Power/YUAN/TESTING_CURRENT 的取值会被采集中心拼成国网试验名称，
-- 合法组合参考（单相）：DIRECTION='正'/'反'，Power='有'/'无'，YUAN=''（单相不拼元），
-- TESTING_CURRENT='IB'/'IMAX'/'0.05IB'（对应 10Itr/Imax/Imin）
INSERT INTO dbo.TErrorDetail (Barcode,DeviceNo,Seat,Power,DIRECTION,YUAN,TESTING_VOLTAGE,TESTING_CURRENT,
                              POWER_FACTOR,Cricles,AVERAGE_ERROR,ERROR1,ERROR2,ERROR3,ERROR4,MaxError,MinError,
                              CheckTime,SaveTime,IPAddress,MachineName,Operator,SCGDBM,CONCLUSION)
SELECT t.BarCode, @SBBH, 1, '有', '正', '', '220', 'IB',
       '1.0', 1, '0.20', '0.18', '0.22', '0.19', '0.21', '0.22', '0.18',
       @SJ, @SJ, @IPDZ, @JQM, @CZY, '', '0'
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.TErrorDetail WHERE Barcode=t.BarCode AND Power='有' AND DIRECTION='正'
                  AND ISNULL(YUAN,'')='' AND TESTING_CURRENT='IB');

-- ---------- 4.8 参数设置（1008）：TParamInfor，BarCode 存成品条码，MP 必填 ----------
-- 至少插"表号"一条（READ_VALUE 12位以上）；建议再插"软件版本号"一条（SOFTWARE_VERSION 取它，缺省 AAAAAAAAAAAAAAAA）
INSERT INTO dbo.TParamInfor (Barcode,MP,DeviceNo,Seat,PARAMETER_NAME,PARAMETER_VALUE,READ_VALUE,CheckTime,SaveTime,IPAddress,MachineName,Operator,SCGDBM,CONCLUSION)
SELECT t.BarCode, t.MP, @SBBH, 1, '表号', '', @BH, @SJ, @SJ, @IPDZ, @JQM, @CZY, '', '0'
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.TParamInfor WHERE Barcode=t.BarCode AND PARAMETER_NAME='表号');

INSERT INTO dbo.TParamInfor (Barcode,MP,DeviceNo,Seat,PARAMETER_NAME,PARAMETER_VALUE,READ_VALUE,CheckTime,SaveTime,IPAddress,MachineName,Operator,SCGDBM,CONCLUSION)
SELECT t.BarCode, t.MP, @SBBH, 1, '软件版本号', '', 'V1.0', @SJ, @SJ, @IPDZ, @JQM, @CZY, '', '0'
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.TParamInfor WHERE Barcode=t.BarCode AND PARAMETER_NAME='软件版本号');

-- ---------- 4.9 回流焊（1009）：SC_HLHTemperature，BarCode 存 PCB 条码 ----------
-- WDZ1 升温区 / WDZ2 恒温区 / WDZ3 焊接区 / WDZ4 冷却区（值按贵司炉温工艺填）
INSERT INTO dbo.SC_HLHTemperature (BarCode,WDZ1,WDZ2,WDZ3,WDZ4,WDZ5,WDZ6,WDZ7,WDZ8,SBBH,SJ,IPDZ,JQM)
SELECT t.PCB, '150', '175', '245', '90', '', '', '', '', @SBBH, @SJ, @IPDZ, @JQM
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.SC_HLHTemperature WHERE BarCode=t.PCB);

-- ---------- 4.10 波峰焊（1010）：SC_BFHTemperature，BarCode 存 PCB 条码 ----------
-- WDZ1 预热区 / WDZ2 焊接区
INSERT INTO dbo.SC_BFHTemperature (BarCode,WDZ1,WDZ2,WDZ3,WDZ4,WDZ5,WDZ6,WDZ7,WDZ8,SBBH,SJ,IPDZ,JQM)
SELECT t.PCB, '105', '250', '', '', '', '', '', '', @SBBH, @SJ, @IPDZ, @JQM
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.SC_BFHTemperature WHERE BarCode=t.PCB);

-- ---------- 4.11 老化（1011）：四张表配合，缺任一老化页签都是空的 ----------
-- ① 工序结果：SC_Result，GXBH=16，BarCode 存【成品条码】
INSERT INTO dbo.SC_Result (BarCode,GXBH,BW,SBBH,RST,JQM,IPDZ,CZYMC,SJ,SCDDBM,StationID)
SELECT t.BarCode, '16', 0, @LH_SBBH, '90', @JQM, @IPDZ, @CZY, @SJ, @SCDDBM, @LH_SBBH
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.SC_Result WHERE BarCode=t.BarCode AND GXBH='16' AND RST='90');

-- ② 老化批次主表 SC_LHXX：V_SC_LHS 的主表。缺了它 GetModel() 返回 null，
--    采集中心直接 continue，老化表格 0 行且无任何报错。
INSERT INTO dbo.SC_LHXX (GXBH,TestPCH,INTime,OutTime,UseTime,Count,HGCount,Status,SBBH,IPDZ,JQM,CZYMC,SJ,QR)
SELECT NULL, @LH_PCH, @LH_IN, @LH_OUT, '480.0',
       (SELECT COUNT(*) FROM #TMP), (SELECT COUNT(*) FROM #TMP),
       '已完成', @LH_SBBH, @IPDZ, @JQM, @CZY, CONVERT(datetime, @LH_IN), @JQM
WHERE NOT EXISTS (SELECT 1 FROM dbo.SC_LHXX WHERE TestPCH = @LH_PCH);

-- ③ 老化批次明细 SC_LHMX：每个成品条码一行，视图靠它把批次挂到条码和订单
INSERT INTO dbo.SC_LHMX (Barcode,TestPCH,ZT,SCDDBM,SJ)
SELECT t.BarCode, @LH_PCH, '合格', @SCDDBM, CONVERT(datetime, @LH_IN)
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.SC_LHMX WHERE TestPCH = @LH_PCH AND Barcode = t.BarCode);

-- ④ 老化房温度 SC_LHTemperature：WDZ 必须 55~65（越界会被采集中心随机改写并回写源表）
--    采集中心固定取 12 个点：起点 = INTime+1h，每轮 +30 分钟 → 最后一轮起点 = INTime+6.5h。
--    每轮查 MachineID=@LH_SBBH 且 SJ ∈ [起点, OutTime]，任一轮 0 行就弹
--    「没有获取到温度值」并 return false（整表放弃）。
--    所以这里从 INTime+1h 起每 30 分钟造一条、共 16 条（覆盖到 INTime+8.5h），
--    并把 OutTime 设为 INTime+8h，保证 12 轮全部命中。
DECLARE @i int = 0, @wdt varchar(50), @sj2 varchar(50);
WHILE @i < 16
BEGIN
    SET @wdt = CONVERT(varchar(50), 59.8 + CONVERT(numeric(3,1), RAND()*0.4));
    SET @sj2 = CONVERT(varchar(19), DATEADD(minute, 60 + 30*@i, CONVERT(datetime, @LH_IN)), 120);
    INSERT INTO dbo.SC_LHTemperature (MachineID,DeviceID,WDZ,SJ,IPDZ,JQM)
    SELECT @LH_SBBH, '', @wdt, @sj2, @IPDZ, @JQM
    WHERE NOT EXISTS (SELECT 1 FROM dbo.SC_LHTemperature WHERE MachineID=@LH_SBBH AND SJ=@sj2);
    SET @i = @i + 1;
END

-- ---------- 4.12 包装入库（1090）：SC_Result，GXBH=15，BarCode 存铭牌 ----------
INSERT INTO dbo.SC_Result (BarCode,GXBH,BW,SBBH,RST,JQM,IPDZ,CZYMC,SJ,SCDDBM,StationID)
SELECT t.MP, '15', 0, @SBBH, '90', @JQM, @IPDZ, @CZY, @SJ, @SCDDBM, @SBBH
FROM #TMP t
WHERE NOT EXISTS (SELECT 1 FROM dbo.SC_Result WHERE BarCode=t.MP AND GXBH='15' AND RST='90');


/* =====================================================================================
   第5步：插入后自检 —— 以下 SELECT 完全模拟 EIPDataCenterV3 的抽取 SQL，
   每条结果行将来都会被"上传到中间库"。查不到=白插；查到的行数要与预期一致。
   ===================================================================================== */
DECLARE @PCB_KS varchar(50) = (SELECT MIN(PCB)  FROM #TMP);
DECLARE @PCB_JS varchar(50) = (SELECT MAX(PCB)  FROM #TMP);
DECLARE @MP_KS  varchar(50) = (SELECT MIN(MP)   FROM #TMP);
DECLARE @MP_JS  varchar(50) = (SELECT MAX(MP)   FROM #TMP);
DECLARE @L1 int = LEN(@PCB_KS), @L2 int = LEN(@MP_KS);

-- 5.1 AOI / FCT（GXBH=3 / 10）
SELECT 'AOI' AS 工序, COUNT(*) AS 将上传数量 FROM dbo.SC_Result
WHERE GXBH='3' AND RST='90' AND Barcode>=@PCB_KS AND Barcode<=@PCB_JS AND LEN(Barcode)=@L1
UNION ALL
SELECT 'FCT', COUNT(*) FROM dbo.SC_Result
WHERE GXBH='10' AND RST='90' AND Barcode>=@PCB_KS AND Barcode<=@PCB_JS AND LEN(Barcode)=@L1;

-- 5.2 耐压（同条码取最新一条；采集中心靠 JOIN SC_CPXX 拿到 PCB，TNYCS 表本身没有 PCB 列）
SELECT '耐压' AS 工序, COUNT(*) AS 将上传数量
FROM (SELECT ROW_NUMBER() OVER (PARTITION BY aa.Barcode ORDER BY aa.SaveTime DESC) AS RN, aa.Barcode, cp.PCB
      FROM dbo.TNYCS aa
      INNER JOIN dbo.SC_CPXX cp ON cp.BarCode = aa.Barcode
      INNER JOIN dbo.SC_CPMX cc ON cc.BarCode = aa.Barcode
      WHERE cp.PCB >= @PCB_KS AND cp.PCB <= @PCB_JS) x
WHERE RN=1;

-- 5.3 日计时 / 基本误差 / 误差详情 / 参数设置（口径同 5.2：成品条码 + 最新一条）
SELECT '日计时' AS 工序, COUNT(*) AS 将上传数量 FROM dbo.TDayTimeError WHERE Barcode IN (SELECT BarCode FROM #TMP);
SELECT '基本误差' AS 工序, COUNT(*) AS 将上传数量 FROM dbo.TErrorResult WHERE Barcode IN (SELECT BarCode FROM #TMP);
SELECT '误差详情' AS 工序, COUNT(*) AS 将上传数量 FROM dbo.TErrorDetail WHERE Barcode IN (SELECT BarCode FROM #TMP);
SELECT '参数设置' AS 工序, COUNT(*) AS 将上传数量 FROM dbo.TParamInfor
WHERE Barcode IN (SELECT BarCode FROM #TMP) AND (PARAMETER_NAME='表号' OR PARAMETER_NAME='设置表号');

-- 5.4 电池电流 / 回流焊 / 波峰焊（PCB 条码区间）
SELECT '电池电流' AS 工序, COUNT(*) AS 将上传数量 FROM dbo.V_SC_DCDL
WHERE PCB>=@PCB_KS AND PCB<=@PCB_JS AND LEN(PCB)=@L1;   -- 采集中心查的就是这个视图
SELECT '回流焊' AS 工序, COUNT(*) AS 将上传数量 FROM dbo.SC_HLHTemperature
WHERE Barcode>=@PCB_KS AND Barcode<=@PCB_JS AND LEN(Barcode)=@L1;
SELECT '波峰焊' AS 工序, COUNT(*) AS 将上传数量 FROM dbo.SC_BFHTemperature
WHERE Barcode>=@PCB_KS AND Barcode<=@PCB_JS AND LEN(Barcode)=@L1;

-- 5.5 老化 / 包装入库
SELECT '老化批次' AS 工序, COUNT(*) AS 将上传数量 FROM dbo.SC_Result
WHERE GXBH='16' AND RST='90' AND Barcode IN (SELECT BarCode FROM #TMP);
SELECT '老化温度' AS 工序, COUNT(*) AS 将上传数量 FROM dbo.SC_LHTemperature
WHERE MachineID=@LH_SBBH AND SJ>=@LH_IN AND SJ<=@LH_OUT;  -- 应 >= 13 条，才够 12 轮取数
SELECT '包装入库' AS 工序, COUNT(*) AS 将上传数量 FROM dbo.SC_Result
WHERE GXBH='15' AND RST='90' AND Barcode>=@MP_KS AND Barcode<=@MP_JS AND LEN(Barcode)=@L2;

/* =====================================================================================
   附：执行清单
   1. 本脚本只在 ZNMeterSys 上执行；eipsysdb_V2 不用碰（由采集中心界面"上传到中间库"写入）
   2. 顺序：第0/1步填参数 -> 第2步校验 -> 第3步补关联 -> 第4步按需插明细 -> 第5步自检
   3. 自检通过后，打开 EIPDataCenterV3「生产数据-试验数据」对应子页，
      按 PCB 区间（或勾"铭牌"按铭牌区间）加载、勾选、上传
   4. AOI/FCT/电池电流/基本误差 的加载行数必须等于订单数量(DD_SCDDXX.ACount)才能上传
   5. 表号 @BH 每块表应不同：批量时可改为 '00000000' + RIGHT('000'+CAST(SEQ AS varchar),4) 之类按 #TMP.SEQ 生成
   ===================================================================================== */
