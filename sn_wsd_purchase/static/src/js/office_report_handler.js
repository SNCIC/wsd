import { download } from "@web/core/network/download";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

/** Report type produced by the Word builder of the module. */
const OFFICE_REPORT_TYPES = ["docx"];
const DOWNLOAD_URL = "/sn_wsd_purchase/report/office_download";

/**
 * Report handler of the `docx` report actions.
 *
 * The web client only converts PDF and text reports, so the Word contracts are
 * streamed by the controller of the module instead of `/report/download`.
 *
 * @param {Object} action the report action
 * @param {Object} options
 * @param {Object} env the environment of the action manager
 * @returns {Promise<boolean>} true when the report was downloaded
 */
async function downloadOfficeReport(action, options, env) {
    if (!OFFICE_REPORT_TYPES.includes(action.report_type)) {
        return false;
    }
    const activeIds = (action.context && action.context.active_ids) || [];
    const downloadContext = { ...user.context, ...(action.context || {}) };
    env.services.ui.block();
    try {
        await download({
            url: DOWNLOAD_URL,
            data: {
                data: JSON.stringify([
                    action.report_name,
                    action.report_type,
                    activeIds.join(","),
                ]),
                context: JSON.stringify(downloadContext),
            },
        });
    } finally {
        env.services.ui.unblock();
    }
    return true;
}

registry
    .category("ir.actions.report handlers")
    .add("sn_wsd_purchase_office_report", downloadOfficeReport);
