/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

const MIN_SCALE = 0.2;
const MAX_SCALE = 4;
const ZOOM_STEP = 1.25;

/**
 * Full size image viewer: zoom (buttons, slider, wheel), rotate, pan and
 * download. Opened by the "image_viewer" field widget on click.
 */
export class ImageViewerDialog extends Component {
    static template = "sn_wsd_mrp.ImageViewerDialog";
    static components = { Dialog };
    static props = {
        title: { type: String, optional: true },
        url: String,
        filename: { type: String, optional: true },
        close: { type: Function, optional: true },
    };
    static defaultProps = {
        title: _t("Image"),
        filename: "image.png",
    };

    setup() {
        this.state = useState({
            scale: 1,
            rotation: 0,
            offsetX: 0,
            offsetY: 0,
        });
        this.dragStart = null;
    }

    get imageStyle() {
        const { offsetX, offsetY, rotation, scale } = this.state;
        return (
            `transform: translate(${offsetX}px, ${offsetY}px) ` +
            `rotate(${rotation}deg) scale(${scale});`
        );
    }

    get zoomPercent() {
        return Math.round(this.state.scale * 100);
    }

    get isZoomed() {
        return this.state.scale !== 1 || this.state.rotation !== 0;
    }

    get labels() {
        return {
            download: _t("Download"),
            reset: _t("Reset"),
            rotateLeft: _t("Rotate left"),
            rotateRight: _t("Rotate right"),
            zoomIn: _t("Zoom in"),
            zoomOut: _t("Zoom out"),
        };
    }

    setScale(scale) {
        this.state.scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
    }

    zoom(factor) {
        this.setScale(Math.round(this.state.scale * factor * 100) / 100);
    }

    onZoomIn() {
        this.zoom(ZOOM_STEP);
    }

    onZoomOut() {
        this.zoom(1 / ZOOM_STEP);
    }

    onScaleInput(ev) {
        this.setScale(Number(ev.target.value) / 100);
    }

    onRotateLeft() {
        this.state.rotation -= 90;
    }

    onRotateRight() {
        this.state.rotation += 90;
    }

    onReset() {
        this.state.scale = 1;
        this.state.rotation = 0;
        this.state.offsetX = 0;
        this.state.offsetY = 0;
    }

    onWheel(ev) {
        ev.preventDefault();
        this.zoom(ev.deltaY < 0 ? 1.12 : 1 / 1.12);
    }

    onPointerDown(ev) {
        if (ev.button !== 0) {
            return;
        }
        this.dragStart = {
            clientX: ev.clientX,
            clientY: ev.clientY,
            offsetX: this.state.offsetX,
            offsetY: this.state.offsetY,
        };
        ev.currentTarget.setPointerCapture(ev.pointerId);
    }

    onPointerMove(ev) {
        if (!this.dragStart) {
            return;
        }
        this.state.offsetX = this.dragStart.offsetX + (ev.clientX - this.dragStart.clientX);
        this.state.offsetY = this.dragStart.offsetY + (ev.clientY - this.dragStart.clientY);
    }

    onPointerUp(ev) {
        this.dragStart = null;
        if (ev.currentTarget.hasPointerCapture?.(ev.pointerId)) {
            ev.currentTarget.releasePointerCapture(ev.pointerId);
        }
    }

    onDoubleClick() {
        if (this.isZoomed) {
            this.onReset();
        } else {
            this.setScale(2);
        }
    }
}
