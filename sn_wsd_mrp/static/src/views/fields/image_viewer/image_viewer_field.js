/** @odoo-module **/
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { isBinarySize } from "@web/core/utils/binary";
import { useOwnedDialogs } from "@web/core/utils/hooks";
import { imageUrl } from "@web/core/utils/urls";
import {
    fileTypeMagicWordMap,
    ImageField,
    imageField,
} from "@web/views/fields/image/image_field";
import { ImageViewerDialog } from "./image_viewer_dialog";

/**
 * Image widget opening a full size viewer (zoom, rotate, pan, download) when
 * the picture itself is clicked. Upload/clear controls of the standard image
 * widget are kept untouched.
 *
 * Usage in a view:
 *   <field name="image_128" widget="image_viewer"
 *          options="{'size': [40, 40], 'viewer_image': 'image_1920'}"/>
 */
export class ImageViewerField extends ImageField {
    static template = "sn_wsd_mrp.ImageViewerField";
    static props = {
        ...ImageField.props,
        viewerImage: { type: String, optional: true },
    };

    setup() {
        super.setup();
        this.addDialog = useOwnedDialogs();
    }

    get hasImage() {
        return Boolean(this.props.record.data[this.props.name]) && this.state.isValid;
    }

    /**
     * In form views the value is the raw base64 string: use it directly so an
     * unsaved upload can be previewed. In list views it is only a size summary,
     * so fall back to the /web/image route of the configured viewer field.
     */
    getViewerUrl() {
        const value = this.props.record.data[this.props.name];
        if (value && typeof value === "string" && !isBinarySize(value)) {
            const type = fileTypeMagicWordMap[value[0]] || "png";
            return `data:image/${type};base64,${value}`;
        }
        const fieldName = this.props.viewerImage || this.props.name;
        return imageUrl(this.props.record.resModel, this.props.record.resId, fieldName, {
            unique: this.props.record.data.write_date,
        });
    }

    onClickImage(ev) {
        if (ev.target.tagName !== "IMG" || !this.hasImage) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        const model = this.props.record.resModel.split(".").pop();
        this.addDialog(ImageViewerDialog, {
            title: _t("Image"),
            url: this.getViewerUrl(),
            filename: `${model}_${this.props.record.resId || "new"}.png`,
        });
    }
}

export const imageViewerField = {
    ...imageField,
    component: ImageViewerField,
    displayName: _t("Image Viewer"),
    supportedOptions: [
        ...imageField.supportedOptions,
        {
            label: _t("Viewer image"),
            name: "viewer_image",
            type: "field",
            availableTypes: ["binary"],
            help: _t("Field serving the full size image opened in the viewer."),
        },
    ],
    extractProps: (fieldInfo, dynamicInfo) => ({
        ...imageField.extractProps(fieldInfo, dynamicInfo),
        viewerImage: (fieldInfo.options || {}).viewer_image,
    }),
};

registry.category("fields").add("image_viewer", imageViewerField);
