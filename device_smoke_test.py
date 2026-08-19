# -*- coding: utf-8 -*-
# 设备管理模块(sn_wsd_device)全功能冒烟测试,在 odoo shell 中运行
import traceback
from datetime import date, timedelta
from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command

PASS, FAIL = [], []

def T(section, item, fn):
    try:
        note = fn() or ''
        env.cr.commit()
        PASS.append((section, item))
        print('PASS | %s | %s | %s' % (section, item, note))
    except Exception as e:
        env.cr.rollback()
        FAIL.append((section, item, str(e)))
        print('FAIL | %s | %s | %s' % (section, item, e))

env = env  # noqa (shell 提供)
today = date.today()

# ---------- 0. 全模型视图与读取校验 ----------
dev_models = env['ir.model'].browse(
    env['ir.model.data'].search(
        [('module', '=', 'sn_wsd_device'), ('model', '=', 'ir.model')]
    ).mapped('res_id')).sorted('model')
print('=== 共 %d 个模型 ===' % len(dev_models))
for m in dev_models:
    T('视图', m.model, lambda m=m: (
        env[m.model].get_views([(False, 'form'), (False, 'list')]) and
        'form+list arch OK') or '')
    T('读取', m.model, lambda m=m: 'search %d 条' % len(env[m.model].search([])))

# ---------- 通用智能建值 ----------
def fill_required(model, rec_cache, overrides):
    flds = env[model].fields_get()
    vals = dict(overrides)
    for fname, spec in flds.items():
        if fname in vals or not spec.get('required', False):
            continue
        if spec.get('readonly') and not spec.get('store', True):
            continue
        t = spec['type']
        if t == 'char' or t == 'text' or t == 'html':
            vals[fname] = '<p>TEST</p>' if t == 'html' else 'TEST-' + fname
        elif t == 'selection':
            opts = [o[0] for o in spec['selection']]
            pick = 'daily' if 'daily' in opts else opts[0]
            vals[fname] = pick
        elif t == 'date':
            vals[fname] = str(today)
        elif t == 'datetime':
            vals[fname] = str(fields.Datetime.now())
        elif t == 'many2one':
            rel = spec['relation']
            if rel == 'res.company':
                vals[fname] = env.company.id
            elif 'equipment_type' in rel:
                vals[fname] = rec_cache['type'].id
            elif rel.endswith('location'):
                vals[fname] = rec_cache['loc'].id
            elif rel.endswith('equipment'):
                vals[fname] = rec_cache['eq'].id
            else:
                vals[fname] = smart_create(rel, rec_cache, {}).id
        elif t in ('integer', 'float'):
            vals[fname] = 1
        elif t == 'boolean':
            vals[fname] = True
    return vals

def smart_create(model, rec_cache, overrides):
    return env[model].create(fill_required(model, rec_cache, overrides))

# ---------- 1. 设备台账 ----------
cache = {}
def get_or_create(model, vals, key):
    rec = env[model].search([(k, '=', v) for k, v in key.items()], limit=1)
    return rec or env[model].create(vals)

T('台账', '设备类型', lambda: cache.__setitem__('type',
    get_or_create('sn.wsd.device.equipment.type', {'name': 'TEST-回流焊'}, {'name': 'TEST-回流焊'}))
    or 'created/exists TEST-回流焊')
T('台账', '设备位置', lambda: cache.__setitem__('loc',
    get_or_create('sn.wsd.device.location', {'name': 'TEST-SMT车间'}, {'name': 'TEST-SMT车间'}))
    or 'created/exists')
T('台账', '设备建档', lambda: cache.__setitem__('eq',
    get_or_create('sn.wsd.device.equipment',
        dict(fill_required('sn.wsd.device.equipment', cache,
             {'code': 'TEST-EQ-001', 'name': '测试回流炉', 'equipment_status': 'enabled',
              'equipment_type_id': cache['type'].id, 'location_id': cache['loc'].id})),
        {'code': 'TEST-EQ-001'}))
    or '状态=%s' % cache['eq'].equipment_status)

# ---------- 2. 设备文档 ----------
doc_models = [m.model for m in dev_models if 'document' in m.model]
for dm in doc_models:
    T('文档', dm, lambda dm=dm: smart_create(dm, cache, {'name': 'TEST-文档'}) and 'created')

# ---------- 3. 数据采集(回流焊/波峰焊) ----------
def test_collect(record_model, zone_model, label):
    rec = smart_create(record_model, cache, {'device_sn': 'SN-TEST-001'})
    # 找到 zone 上指向 record 的 m2o 字段名
    zfg = env[zone_model].fields_get()
    inverse = [f for f, s in zfg.items()
               if s['type'] == 'many2one' and s['relation'] == record_model][0]
    zone = env[zone_model].create(fill_required(zone_model, cache,
        {inverse: rec.id, 'zone_name': 'Z1', 'temperature': 235.5}))
    return '%s#%d +%s=%s(%.1f℃)' % (label, rec.id, zone.zone_name, inverse, zone.temperature)

for rm in [m.model for m in dev_models if m.model.endswith('.record')]:
    zm = rm.replace('.record', '.zone')
    if zm in [m.model for m in dev_models]:
        T('采集', rm, lambda rm=rm, zm=zm: test_collect(rm, zm, ''))

# ---------- 4/5/6. 点检/保养/校准 闭环 ----------
# 触发时间提前到 00:01,让 cron 逻辑当下即可生成
env['ir.config_parameter'].sudo().set_param('equipment_inspection_trigger_time', '00:01')
env['ir.config_parameter'].sudo().set_param('equipment_maintenance_trigger_time', '00:01')
env['ir.config_parameter'].sudo().set_param('equipment_cal_trigger_time', '00:01')

# 保养模板(保养/点检生成时会引用): 必须同时有保养条目和点检条目,
# 否则任务生成会记为 'no spot check item on the template' 失败
tmpl_models = [m.model for m in dev_models if m.model.endswith('.maint.template')]
for tm in tmpl_models:
    def make_template(tm=tm):
        old = env[tm].search([('equipment_type_id', '=', cache['type'].id)], limit=1)
        if old:
            return '复用模板#%d(保养%d条/点检%d条)' % (
                old.id, len(old.maintenance_item_ids), len(old.spot_check_item_ids))
        fgs = env[tm].fields_get()
        ov = {'equipment_type_id': cache['type'].id}
        for f, s in fgs.items():
            if s['type'] == 'one2many' and s['relation'] == 'sn.wsd.device.maint.item':
                kind = 'spot_check' if 'spot' in f else 'maintenance'
                ov[f] = [Command.create({'name': 'TEST-' + kind, 'item_type': kind})]
        rec = smart_create(tm, cache, ov)
        return '模板#%d(保养%d条/点检%d条)' % (rec.id, len(rec.maintenance_item_ids), len(rec.spot_check_item_ids))
    T('保养', tm + ' 建模板', make_template)

def run_closed_loop(section, plan_model, cron_name, task_model, plan_vals, log_model=None):
    # 清理测试设备今日的旧任务与生成日志,重置台账日期,保证可重复执行
    eq = cache['eq']
    env[task_model].search([('equipment_id', '=', eq.id)]).unlink()
    if log_model:
        env[log_model].search([]).unlink()
    for f, s in eq.fields_get().items():
        if f.startswith('last_') and s['type'] in ('datetime', 'date'):
            eq[f] = False
    dom = [(k, '=', v) for k, v in plan_vals.items() if k in ('equipment_type_id', 'equipment_id')]
    plan = env[plan_model].search(dom, limit=1) or env[plan_model].create(plan_vals)
    plan.write(plan_vals)
    getattr(env[plan_model], cron_name)()
    task = env[task_model].search([('equipment_id', '=', eq.id)], limit=1, order='id desc')
    assert task, '%s 生成后未找到设备任务' % section
    task.action_start()
    assert task.task_status == 'in_progress', '开始后状态=%s' % task.task_status
    # 填写所有行的结果(量程类自动判定,其余置 pass);校准任务还需任务级总评
    for line in task.line_ids:
        if not line.line_result:
            line.line_result = 'pass'
    if 'overall_result' in task._fields and not task.overall_result:
        task.overall_result = 'pass'
    task.action_submit()
    assert task.task_status == 'completed', '提交后状态=%s' % task.task_status
    n_log = len(env[log_model].search([])) if log_model else 0
    return '计划#%d→任务#%d(%s,%s,%d行)→完成 | 生成日志%d条 | 台账回写=%s' % (
        plan.id, task.id, task.task_status, task.overall_result or '-',
        len(task.line_ids), n_log, eq.last_spot_check_date or '-')

# 点检: 周期 daily,今日到期
T('点检', '计划→生成→执行→提交',
  lambda: run_closed_loop('check', 'sn.wsd.device.check.plan',
                          '_cron_generate_check_tasks', 'sn.wsd.device.check.task',
                          {'equipment_type_id': cache['type'].id, 'cycle_type': 'daily',
                           'start_date': str(today - timedelta(days=1))},
                          log_model='sn.wsd.device.check.generation.log'))

# 保养: 周期 daily
T('保养', '模板→计划→生成→执行→提交',
  lambda: run_closed_loop('maint', 'sn.wsd.device.maint.plan',
                          '_cron_generate_maintenance_tasks', 'sn.wsd.device.maint.task',
                          {'equipment_type_id': cache['type'].id, 'cycle_type': 'daily',
                           'start_date': str(today - timedelta(days=1))},
                          log_model='sn.wsd.device.maint.generation.log'))

# 校准: 首校 400 天前,年周期 → 已到期(字段名 initial_cal_date)
T('校准', '计划→生成→执行→提交',
  lambda: run_closed_loop('cal', 'sn.wsd.device.cal.plan',
                          '_cron_generate_calibration_tasks', 'sn.wsd.device.cal.task',
                          {'equipment_id': cache['eq'].id, 'cycle_type': 'yearly',
                           'cycle_count': 1, 'initial_cal_date': str(today - timedelta(days=400)),
                           'advance_days': 30},
                          log_model='sn.wsd.device.cal.generation.log'))

# ---------- 6.5 设备维修闭环 ----------
def repair_loop():
    RO = 'sn.wsd.device.repair.order'
    env[RO].search([('equipment_id', '=', cache['eq'].id)]).with_context(
        allow_repair_order_write=True).unlink()
    # 报修(模拟新建维修单向导提交)
    wiz = env['sn.wsd.device.repair.create.wizard'].create({
        'equipment_id': cache['eq'].id,
        'fault_phenomenon': '<p>TEST 运行异响随即停机</p>',
        'initial_handling': '<p>TEST 检查电源与主轴</p>',
        'is_downtime': True,
        'fault_type': 'mechanical',
        'fault_level': 'critical',
    })
    wiz.action_submit()
    order = env[RO].search(
        [('equipment_id', '=', cache['eq'].id)], limit=1, order='id desc')
    assert order and order.state == 'pending', '提交后状态=%s' % order.state
    assert order.name and order.name != '/', '维修单号未生成'
    assert order.company_id == cache['eq'].company_id, '公司未随设备带出'
    # 接单(任何人都可接,走接单向导)
    env['sn.wsd.device.repair.accept.wizard'].create(
        {'repair_order_id': order.id}).action_confirm()
    order.invalidate_recordset()
    assert order.state == 'repairing', '接单后状态=%s' % order.state
    assert order.accept_user_id and order.accept_time, '接单人/时间未写入'
    assert order.accept_duration_hours >= 0, '接单用时未计算'
    # 记录维修 1: 现场维修(只记录不完成)
    env['sn.wsd.device.repair.record.wizard'].create({
        'repair_order_id': order.id, 'repair_type': 'onsite',
        'repair_process': '<p>TEST 更换主轴轴承</p>',
    }).action_save_record()
    order.invalidate_recordset()
    assert len(order.record_ids) == 1, '维修记录未生成'
    assert order.repair_user_id and order.repair_time, '维修人/时间未随记录更新'
    # 委外维修缺联系人必须被 R13 拦截(savepoint 模拟 web 请求的整体回滚,
    # 否则约束抛错前已 INSERT 的行会留在 shell 事务里)
    try:
        with env.cr.savepoint():
            env['sn.wsd.device.repair.record.wizard'].create({
                'repair_order_id': order.id, 'repair_type': 'outsourced',
                'vendor_company': 'TEST-外协厂',
            }).action_save_record()
        raise AssertionError('委外缺联系人/电话/预计完成时间应报错')
    except ValidationError:
        pass
    # 记录维修 2 + 完成维修: 委外
    env['sn.wsd.device.repair.record.wizard'].create({
        'repair_order_id': order.id, 'repair_type': 'outsourced',
        'vendor_company': 'TEST-外协厂', 'contact_person': 'TEST-张三',
        'contact_phone': '13800000000',
        'expected_completion_time': fields.Datetime.now(),
    }).action_complete_repair()
    order.invalidate_recordset()
    assert order.state == 'done', '完成后状态=%s' % order.state
    assert len(order.record_ids) == 2, '完成时记录数=%d' % len(order.record_ids)
    assert order.completion_time and order.repair_duration_hours >= 0, '完成信息未写入'
    cache['eq'].invalidate_recordset()
    assert cache['eq'].last_repair_date == order.completion_time, '台账未回写最近维修'
    # R12 完成后只读
    try:
        order.write({'fault_level': 'minor'})
        raise AssertionError('完成后应禁止修改')
    except UserError:
        pass
    return '单%s %s 记录%d条 接单%.2fh 维修%.2fh' % (
        order.name, order.state, len(order.record_ids),
        order.accept_duration_hours, order.repair_duration_hours)

T('维修', '报修→接单→记录×2→完成→只读', repair_loop)

# ---------- 7. 逾期标记逻辑 ----------
T('逻辑', '昨日未完成任务自动逾期', lambda: (
    env['sn.wsd.device.check.task']._mark_previous_unfinished_overdue()) and 'ok')

# ---------- 8. 向导 default_get ----------
for wm in [m.model for m in dev_models if m.transient]:
    T('向导', wm, lambda wm=wm: 'defaults=%s' % list(env[wm].default_get(
        list(env[wm].fields_get().keys())).keys()))

env.cr.commit()
print()
print('========== 汇总: PASS %d / FAIL %d ==========' % (len(PASS), len(FAIL)))
for sec, item, err in FAIL:
    print('FAILED: %s -> %s: %s' % (sec, item, err))
