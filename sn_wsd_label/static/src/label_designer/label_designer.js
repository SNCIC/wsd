import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import { Component, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const ELEMENT_TYPE_LABELS = {
    text: _t("Text"),
    qrcode: _t("QR Code"),
    barcode: _t("Barcode"),
    box: _t("Box"),
    line: _t("Line"),
};

// sensible defaults for toolbox-created elements (dots @203dpi)
const NEW_ELEMENT_DEFAULTS = {
    text: { x: 24, y: 24, width: 200, height: 32, font_size: 26,
            element_type: "text", content: "fixed", fixed_text: "" },
    qrcode: { x: 420, y: 24, width: 120, height: 120,
              element_type: "qrcode", content: "field", rendering: "native" },
    barcode: { x: 24, y: 250, width: 260, height: 54,
               element_type: "barcode", content: "fixed", fixed_text: "" },
    line: { x: 16, y: 160, width: 400, height: 0, thickness: 2,
            element_type: "line" },
    box: { x: 8, y: 8, width: 544, height: 304, thickness: 2,
           element_type: "box" },
};

/**
 * Label designer canvas: the preview image becomes a full editor.
 *
 * Interactions:
 * - toolbox: add text / QR / barcode / line / box directly on the canvas
 * - property panel: edit the selected element next to the canvas
 *   (content, field, font, geometry) instead of scrolling the list
 * - drag to move, corner handle to resize — the gesture only updates
 *   local state; the record is written once, on pointer release
 * - keyboard: arrows nudge ±1 dot (shift: ±10), Del removes
 * - zoom controls (the layout dots stay authoritative)
 */
export class LabelDesignerField extends Component {
    static template = "sn_wsd_label.LabelDesignerField";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.rootRef = useRef("root");
        // template-facing strings and constants (no _t/ELEMENT_TYPE_LABELS
        // in template scope)
        this.typeLabels = ELEMENT_TYPE_LABELS;
        this.labels = {
            addText: _t("Add a text element"),
            addQrcode: _t("Add a QR code"),
            addBarcode: _t("Add a barcode"),
            addLine: _t("Add a straight line"),
            addBox: _t("Add a box"),
            zoomOut: _t("Zoom out"),
            zoomIn: _t("Zoom in"),
            fitZoom: _t("Fit zoom"),
            clickToEdit: _t("Click an element to edit its properties."),
            nudge: _t("nudge 1 dot (Shift: 10)"),
            removeSelected: _t("remove selected"),
            content: _t("Content"),
            fixedText: _t("Fixed Text"),
            field: _t("Field"),
            fontSize: _t("Font Size"),
            maxLines: _t("Max Lines"),
            align: _t("Align"),
            left: _t("Left"),
            center: _t("Center"),
            right: _t("Right"),
            rendering: _t("Rendering"),
            native: _t("Native"),
            bitmap: _t("Bitmap"),
            thickness: _t("Thickness"),
            deleteElement: _t("Delete element"),
            normalize: _t("Fit out-of-bounds elements"),
            nothingSelected: _t("Nothing selected"),
        };
        this.state = useState({
            selectedId: null,
            zoom: 1,
            fieldOptions: [],
        });
        // gesture is deliberately NON-reactive: during a drag the moved box
        // is updated through direct DOM writes, because re-rendering this
        // component per pointermove would also re-patch the property panel
        // (field select can hold hundreds of options) and cause jitter.
        this._gesture = null;
        this._gestureCleanup = null;
        // a drag in flight when the form navigates away must not leak its
        // window listeners or the global dragging cursor class
        onWillUnmount(() => this._gestureCleanup && this._gestureCleanup());
        useEffect(() => this.fitZoom(), () => [this.width, this.height]);
        useEffect(
            () => {
                this.loadFieldOptions();
            },
            () => [this.record.data.model_name]
        );
    }

    async loadFieldOptions() {
        const model = this.record.data.model_name;
        if (!model) {
            this.state.fieldOptions = [];
            return;
        }
        try {
            this.state.fieldOptions = await this.orm.call(
                "sn.label.reader", "field_path_options", [model]
            );
        } catch {
            this.state.fieldOptions = [];
        }
    }

    get record() {
        return this.props.record;
    }

    get elements() {
        const list = this.record.data.element_ids;
        return list && list.records ? [...list.records] : [];
    }

    get elementList() {
        return this.record.data.element_ids;
    }

    get selectedElement() {
        return this.elements.find((item) => item.id === this.state.selectedId) || null;
    }

    get width() {
        return this.record.data.width_dots || 560;
    }

    get height() {
        return this.record.data.height_dots || 320;
    }

    get dpi() {
        return this.record.data.dpi || 203;
    }

    get mmSize() {
        const mm = (dots) => ((dots / this.dpi) * 25.4).toFixed(1);
        return `${mm(this.width)} × ${mm(this.height)} mm`;
    }

    get imageUrl() {
        return this.props.value
            ? `data:image/png;base64,${this.props.value}`
            : "";
    }

    get canvasStyle() {
        return `width: ${Math.round(this.width * this.state.zoom)}px; height: ${Math.round(
            this.height * this.state.zoom
        )}px;`;
    }

    get saveHint() {
        return _t("Unsaved changes are kept by the form; press Save to refresh the preview.");
    }

    get altText() {
        return _t("Label preview");
    }

    get selectionInfo() {
        const element = this.selectedElement;
        if (!element || !element.data) {
            return _t("Nothing selected");
        }
        const data = element.data;
        return `${this.elementLabel(element)}: ${data.x}, ${data.y} · ${data.width} × ${data.height}`;
    }

    get selectionDeletable() {
        const element = this.selectedElement;
        return Boolean(element && Number.isInteger(element.resId));
    }

    elementLabel(element) {
        const data = element.data;
        if (data.element_type === "text") {
            const label =
                data.content === "field" ? data.field_path : data.fixed_text;
            return label || ELEMENT_TYPE_LABELS.text;
        }
        return ELEMENT_TYPE_LABELS[data.element_type] || data.element_type || "";
    }

    elementStyle(element) {
        const data = element.data;
        const zoom = this.state.zoom;
        const { x, y, width, height } = data;
        const horizontalLine = data.element_type === "line" && height === 0;
        const verticalLine = data.element_type === "line" && width === 0;
        const boxHeight = horizontalLine ? Math.max(4, data.thickness || 2) : height;
        const boxWidth = verticalLine ? Math.max(4, data.thickness || 2) : width;
        let left = x * zoom;
        let top = y * zoom;
        let pxWidth = Math.max(6, (boxWidth || 2) * zoom);
        let pxHeight = Math.max(6, boxHeight * zoom);
        // survive re-renders mid-gesture (autosave can trigger one):
        // render the dragged element where the DOM writes put it
        const gesture = this._gesture;
        if (gesture && gesture.id === element.id) {
            if (gesture.mode === "move") {
                left += gesture.dxPx;
                top += gesture.dyPx;
            } else {
                pxWidth = Math.max(6, pxWidth + gesture.dxPx);
                pxHeight = Math.max(6, pxHeight + gesture.dyPx);
            }
        }
        return [
            `left: ${Math.round(left)}px`,
            `top: ${Math.round(top)}px`,
            `width: ${Math.round(pxWidth)}px`,
            `height: ${Math.round(pxHeight)}px`,
        ].join("; ");
    }

    fitZoom() {
        const root = this.rootRef.el;
        const node = root && root.querySelector(".o_label_designer_canvas");
        if (!node) {
            return;
        }
        const available = (node.parentElement.clientWidth || 480) - 8;
        this.state.zoom = Math.min(1, Math.round((available / this.width) * 100) / 100);
    }

    zoomIn() {
        this.state.zoom = Math.min(3, Math.round((this.state.zoom + 0.15) * 100) / 100);
    }

    zoomOut() {
        this.state.zoom = Math.max(0.3, Math.round((this.state.zoom - 0.15) * 100) / 100);
    }

    // ------------------------------------------------------------------
    // Bounds: keep elements inside the label canvas. Elements clipped by
    // overflow:hidden are invisible and unclickable — better to prevent
    // escapes on every write and offer a rescue for old data.
    // ------------------------------------------------------------------
    _clamp(value, min, max) {
        return Math.min(Math.max(value, min), Math.max(min, max));
    }

    _clampGeometry(data) {
        const width = Math.min(data.width || 1, this.width);
        const height = Math.min(data.height || 1, this.height);
        return {
            x: this._clamp(data.x, 0, this.width - width),
            y: this._clamp(data.y, 0, this.height - height),
            width: this._clamp(width, 1, this.width),
            height: this._clamp(height, 1, this.height),
        };
    }

    async normalizeElements() {
        for (const element of this.elements) {
            const data = element.data;
            const clamped = this._clampGeometry(data);
            if (
                clamped.x !== data.x || clamped.y !== data.y ||
                clamped.width !== data.width || clamped.height !== data.height
            ) {
                await element.update(clamped);
            }
        }
    }

    // ------------------------------------------------------------------
    // Toolbox
    // ------------------------------------------------------------------
    async addElement(type) {
        if (this.props.readonly) {
            return;
        }
        const list = this.elementList;
        if (!list || typeof list.addNewRecord !== "function") {
            return;
        }
        const record = await list.addNewRecord(true);
        if (record) {
            await record.update({ ...NEW_ELEMENT_DEFAULTS[type] });
            this.state.selectedId = record.id;
        }
    }

    async removeSelected() {
        const element = this.selectedElement;
        if (!element || !Number.isInteger(element.resId)) {
            return;
        }
        this.state.selectedId = null;
        await element.delete();
    }

    // ------------------------------------------------------------------
    // Property panel
    // ------------------------------------------------------------------
    onPanelSelect(name, value) {
        this.updateSelected({ [name]: value === "" ? false : value });
    }

    onPanelNumber(name, value) {
        const parsed = parseInt(value, 10);
        const element = this.selectedElement;
        if (!element) {
            return;
        }
        const next = this._clampGeometry({
            ...element.data,
            [name]: Number.isNaN(parsed) ? 0 : parsed,
        });
        this.updateSelected({
            x: next.x,
            y: next.y,
            width: next.width,
            height: next.height,
        });
    }

    async updateSelected(changes) {
        const element = this.selectedElement;
        if (!element || this.props.readonly) {
            return;
        }
        await element.update(changes);
    }

    // ------------------------------------------------------------------
    // Pointer interactions
    // ------------------------------------------------------------------
    onElementPointerDown(ev, element) {
        this._startGesture(ev, element, "move");
    }

    onResizePointerDown(ev, element) {
        this._startGesture(ev, element, "resize");
    }

    // Mouse fallback for environments without pointer event synthesis:
    // real browsers fire pointerdown first (setting the gesture, so the
    // following mousedown is ignored by the active-gesture guard).
    onElementMouseDown(ev, element) {
        this._startGesture(ev, element, "move");
    }

    onResizeMouseDown(ev, element) {
        this._startGesture(ev, element, "resize");
    }

    onCanvasKeydown(ev) {
        const element = this.selectedElement;
        if (this.props.readonly || !element) {
            return;
        }
        const step = ev.shiftKey ? 10 : 1;
        const changes = {
            ArrowLeft: { x: element.data.x - step },
            ArrowRight: { x: element.data.x + step },
            ArrowUp: { y: element.data.y - step },
            ArrowDown: { y: element.data.y + step },
        }[ev.key];
        if (changes) {
            ev.preventDefault();
            const next = this._clampGeometry({
                ...element.data,
                x: changes.x ?? element.data.x,
                y: changes.y ?? element.data.y,
            });
            this.updateSelected({ x: next.x, y: next.y });
        } else if (ev.key === "Delete" || ev.key === "Backspace") {
            ev.preventDefault();
            this.removeSelected();
        }
    }

    _startGesture(ev, element, mode) {
        if (this.props.readonly || this._gesture) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        this.state.selectedId = element.id;
        // resize gestures start on the corner handle span: resolve the
        // element box so geometry writes target it, not the 10px handle
        const node =
            ev.currentTarget.closest(".o_label_designer_element") ||
            ev.currentTarget;
        const zoom = this.state.zoom;
        const startX = ev.clientX;
        const startY = ev.clientY;
        const snapshot = {
            x: element.data.x,
            y: element.data.y,
            width: element.data.width,
            height: element.data.height,
        };
        const baseLeft = snapshot.x * zoom;
        const baseTop = snapshot.y * zoom;
        const baseWidth = (snapshot.width || 2) * zoom;
        const baseHeight = (snapshot.height || 2) * zoom;
        const readout = this.rootRef.el && this.rootRef.el.querySelector(".o_label_designer_selection");
        const label = this.elementLabel(element);
        this._gesture = { id: element.id, mode, dxPx: 0, dyPx: 0 };
        document.body.classList.add("o_label_designer_dragging");

        const applyDom = (dxPx, dyPx) => {
            this._gesture.dxPx = dxPx;
            this._gesture.dyPx = dyPx;
            if (mode === "move") {
                node.style.left = `${Math.round(baseLeft + dxPx)}px`;
                node.style.top = `${Math.round(baseTop + dyPx)}px`;
            } else {
                node.style.width = `${Math.max(6, Math.round(baseWidth + dxPx))}px`;
                node.style.height = `${Math.max(6, Math.round(baseHeight + dyPx))}px`;
            }
            if (readout) {
                const x = Math.max(0, Math.round(snapshot.x + dxPx / zoom));
                const y = Math.max(0, Math.round(snapshot.y + dyPx / zoom));
                const w = Math.max(1, Math.round(snapshot.width + dxPx / zoom));
                const h = Math.max(1, Math.round(snapshot.height + dyPx / zoom));
                readout.textContent = mode === "move"
                    ? `${label}: ${x}, ${y} · ${snapshot.width} × ${snapshot.height}`
                    : `${label}: ${snapshot.x}, ${snapshot.y} · ${w} × ${h}`;
            }
        };
        const onMove = (moveEvent) => {
            if (!this._gesture || this._gesture.id !== element.id) {
                return;
            }
            applyDom(moveEvent.clientX - startX, moveEvent.clientY - startY);
        };
        this._gestureCleanup = () => {
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("pointerup", onUp);
            window.removeEventListener("mouseup", onUp);
            this._gesture = null;
            this._gestureCleanup = null;
            document.body.classList.remove("o_label_designer_dragging");
        };
        const onUp = (upEvent) => {
            this._gestureCleanup();
            // single record write per gesture — the form (element list,
            // property panel incl. the big field select) re-renders once
            const raw = {};
            if (mode === "move") {
                raw.x = Math.round(snapshot.x + (upEvent.clientX - startX) / zoom);
                raw.y = Math.round(snapshot.y + (upEvent.clientY - startY) / zoom);
            } else {
                raw.width = Math.round(snapshot.width + (upEvent.clientX - startX) / zoom);
                raw.height = Math.round(snapshot.height + (upEvent.clientY - startY) / zoom);
            }
            element.update(this._clampGeometry({ ...snapshot, ...raw }));
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("mousemove", onMove);
        window.addEventListener("pointerup", onUp);
        window.addEventListener("mouseup", onUp);
    }
}

export const labelDesignerField = {
    component: LabelDesignerField,
    displayName: _t("Label Designer"),
    supportedTypes: ["binary"],
};

registry.category("fields").add("sn_wsd_label_designer", labelDesignerField);
