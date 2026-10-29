/** @odoo-module **/

import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { ImageField } from "@web/views/fields/image/image_field";

// Models whose image removal must be confirmed before being applied.
const CONFIRM_MODELS = ["product.template", "product.product"];

patch(ImageField.prototype, {
    setup() {
        super.setup();
        this.dialogService = useService("dialog");
        this.isConfirmingRemoval = false;
    },

    /**
     * @override
     * Ask for confirmation before clearing a product image. The removal only
     * changes the record in memory, it is applied to the database on save.
     */
    async onFileRemove() {
        if (!CONFIRM_MODELS.includes(this.props.record.resModel)) {
            return super.onFileRemove();
        }
        if (this.isConfirmingRemoval) {
            // Ignore repeated clicks while the confirmation dialog is open.
            return;
        }
        this.isConfirmingRemoval = true;
        try {
            if (!(await this.confirmImageRemoval())) {
                return;
            }
            return super.onFileRemove();
        } finally {
            this.isConfirmingRemoval = false;
        }
    },

    /**
     * @returns {Promise<boolean>} true when the user confirmed the removal
     */
    confirmImageRemoval() {
        return new Promise((resolve) => {
            this.dialogService.add(
                ConfirmationDialog,
                {
                    title: _t("Delete Image"),
                    body: _t(
                        "Are you sure you want to delete this image? The image will only be removed once the record is saved."
                    ),
                    confirmLabel: _t("Delete"),
                    confirmClass: "btn-danger",
                    confirm: () => resolve(true),
                },
                { onClose: () => resolve(false) }
            );
        });
    },
});
