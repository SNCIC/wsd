/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Domain } from "@web/core/domain";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

// PDA 标签打印屏（决策 7）：选模板 → 按模板 sn_field 扫/输 SN 定位记录 →
// 取 CPCL-JSON 指令 → base64 拼进 printserver:cpcl scheme 唤起 PrintServer
// APP。布局逻辑全部在服务端，前端只做编码与唤起。
export class LabelPrintScreen extends Component {
    static props = { ...standardActionServiceProps };
    static template = "sn_wsd_label.LabelPrintScreen";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.snInputRef = useRef("snInput");
        this.state = useState({
            templates: [],
            templateId: null,
            sn: "",
            record: null,
            copies: 1,
            message: "",
            messageType: "info",
            loading: false,
        });
        onMounted(() => {
            this.loadTemplates();
            this.focusInput();
        });
    }

    get title() {
        return _t("Label Print");
    }

    get templateLabel() {
        return _t("Template");
    }

    get copiesLabel() {
        return _t("Copies");
    }

    get snLabel() {
        return _t("Scan or type the SN");
    }

    get printLabel() {
        return _t("Print");
    }

    get searchLabel() {
        return _t("Find");
    }

    get clearLabel() {
        return _t("Clear");
    }

    get placeholderLabel() {
        return _t("Select a template…");
    }

    get selectedTemplate() {
        const id = Number(this.state.templateId);
        return this.state.templates.find((template) => template.id === id) || null;
    }

    setMessage(message, type = "info") {
        this.state.message = message;
        this.state.messageType = type;
    }

    focusInput() {
        setTimeout(() => this.snInputRef.el?.focus(), 0);
    }

    async loadTemplates() {
        try {
            this.state.templates = await this.orm.searchRead(
                "sn.label.template",
                [["active", "=", true]],
                ["name", "model_name", "sn_field", "domain"],
            );
            if (this.state.templates.length === 1) {
                this.state.templateId = this.state.templates[0].id;
            } else if (!this.state.templates.length) {
                this.setMessage(_t("No active label template available."), "warning");
            }
        } catch (error) {
            this.setMessage(this.errorMessage(error), "danger");
        }
    }

    onTemplateChange() {
        this.state.record = null;
        this.state.sn = "";
        this.setMessage("", "info");
        this.focusInput();
    }

    submitSn(event) {
        event.preventDefault();
        this.findRecord();
    }

    // SN 域 + 模板可选 domain（模板 domain 引用字段时无法前端求值，退回纯 SN 域）
    recordDomain(template, sn) {
        const snDomain = [[template.sn_field, "=", sn]];
        if (!template.domain) {
            return snDomain;
        }
        try {
            return Domain.and([template.domain, snDomain]).toList();
        } catch {
            return snDomain;
        }
    }

    async findRecord() {
        const template = this.selectedTemplate;
        const sn = (this.state.sn || "").trim();
        if (!template) {
            this.setMessage(_t("Select a label template first."), "warning");
            return;
        }
        if (!sn) {
            this.focusInput();
            return;
        }
        this.state.loading = true;
        try {
            const records = await this.orm.searchRead(
                template.model_name,
                this.recordDomain(template, sn),
                ["display_name"],
                { limit: 1 },
            );
            if (records.length) {
                this.state.record = records[0];
                this.setMessage(_t("Record found: %s", records[0].display_name), "success");
            } else {
                this.state.record = null;
                this.setMessage(_t("No record found for SN %s.", sn), "warning");
            }
        } catch (error) {
            this.state.record = null;
            this.setMessage(this.errorMessage(error), "danger");
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }

    clearRecord() {
        this.state.record = null;
        this.state.sn = "";
        this.setMessage("", "info");
        this.focusInput();
    }

    async print() {
        const template = this.selectedTemplate;
        if (!template) {
            this.notification.add(_t("Select a label template first."), { type: "warning" });
            return;
        }
        if (!this.state.record) {
            this.notification.add(_t("Find a record by scanning or typing its SN first."), {
                type: "warning",
            });
            return;
        }
        const copies = Math.max(1, parseInt(this.state.copies, 10) || 1);
        this.state.loading = true;
        try {
            const result = await rpc("/sn_wsd_label/print_commands", {
                template_id: template.id,
                ids: [this.state.record.id],
                copies,
            });
            const payload = btoa(unescape(encodeURIComponent(JSON.stringify(result.commands))));
            window.location.href = "printserver:cpcl?content=" + payload;
            this.notification.add(
                _t("Print commands sent to the PrintServer app."), { type: "success" });
            this.setMessage(
                _t("Print commands sent to the PrintServer app."), "success");
        } catch (error) {
            const message = this.errorMessage(error) || _t("Print failed.");
            this.notification.add(message, { type: "danger" });
            this.setMessage(message, "danger");
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }

    errorMessage(error) {
        return error?.data?.message || error?.message || "";
    }
}

registry.category("actions").add("sn_wsd_label.label_print_screen", LabelPrintScreen);
