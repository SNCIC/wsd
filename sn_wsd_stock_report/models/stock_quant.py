from odoo import models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def _read_group_postprocess_aggregate(self, aggregate_spec, raw_values):
        """按产品/批次批量计算分组聚合里的库存价值，消除逐条 quant 的 N+1 查询。

        stock_account 把 `value:sum` 退化成 `id:recordset`，再在
        `_read_group_postprocess_aggregate` 里对每条 quant 调用 `_compute_value`，
        而 `_compute_value` 每条记录都要单独取一次 `product.qty_available` /
        `product.total_value`。分组加载上千条 quant 时会产生数千次 SQL：实测
        3912 条 quant 需要 4029 次查询、125 秒。这里改成按 (产品|批次, 公司)
        批量取一次总价值和数量，再摊分回各分组。
        """
        if aggregate_spec not in ('value:sum', 'value:sum_currency'):
            return super()._read_group_postprocess_aggregate(aggregate_spec, raw_values)
        return self._read_group_quant_value(raw_values)

    def _read_group_quant_value(self, raw_values):
        raw_values = list(raw_values)
        column = list(super()._read_group_postprocess_aggregate('id:recordset', raw_values))
        quant_ids = list(dict.fromkeys(
            quant.id for records in column for quant in records
        ))
        quants = self.browse(quant_ids)
        quants.fetch(['company_id', 'location_id', 'owner_id', 'product_id', 'quantity', 'lot_id'])
        quants = quants.filtered(lambda quant: (
            quant.company_id
            and quant.location_id
            and quant.product_id
            and quant.location_id._should_be_valued()
            and not quant._should_exclude_for_valuation()
            and not quant.product_id.uom_id.is_zero(quant.quantity)
        ))
        product_valuations, lot_valuations = self._get_quant_valuations(quants)
        # value 的公式保持与 stock_account._compute_value 完全一致，逐条相乘再相加，
        # 保证分组汇总结果与逐条计算的结果逐位相同。
        values = {}
        for quant in quants:
            if quant.product_id.lot_valuated:
                valuation = lot_valuations.get((quant.lot_id.id, quant.company_id.id))
            else:
                valuation = product_valuations.get((quant.product_id.id, quant.company_id.id))
            if valuation:
                total_value, quantity = valuation
                values[quant.id] = quant.quantity * total_value / quantity
        return [sum(values.get(quant.id, 0.0) for quant in records) for records in column]

    def _get_quant_valuations(self, quants):
        """批量取 (产品|批次, 公司) 的总价值与数量，返回 (产品, 批次) 两个字典。"""
        product_valuations = {}
        lot_valuations = {}
        for company in quants.company_id:
            company_quants = quants.filtered(lambda quant: quant.company_id == company)
            lot_quants = company_quants.filtered(lambda quant: quant.product_id.lot_valuated)
            products = (company_quants - lot_quants).product_id
            if products:
                products = products.with_company(company)
                # 一次访问即触发整批产品的计算，而不是每条 quant 各算一次
                quantities = {product.id: product.qty_available
                              for product in products._with_valuation_context()}
                for product in products:
                    quantity = quantities[product.id]
                    if not product.uom_id.is_zero(quantity):
                        product_valuations[(product.id, company.id)] = (product.total_value, quantity)
            lots = lot_quants.lot_id.with_company(company)
            if lots:
                quantities = {lot.id: lot.product_qty for lot in lots}
                for lot in lots:
                    quantity = quantities[lot.id]
                    if not lot.product_id.uom_id.is_zero(quantity):
                        lot_valuations[(lot.id, company.id)] = (lot.total_value, quantity)
        return product_valuations, lot_valuations
