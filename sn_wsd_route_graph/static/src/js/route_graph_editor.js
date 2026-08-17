/** @odoo-module **/
import { registry } from "@web/core/registry";
import { RouteFlowEditor } from "./route_flow_widget";

// The full-screen Graph Editor reuses the same X6 agentFlow-style editor as the
// embedded form widget. It resolves the active process route from the client
// action context.
registry.category("actions").add("sn_wsd_route_graph.editor", RouteFlowEditor);
