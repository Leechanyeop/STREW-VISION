#!/usr/bin/env python3
"""Desktop GUI client for the Jetson Greenhouse server.

The Node/Express server remains the source of truth. This GUI only calls the
HTTP API, so it can run on the Jetson Nano desktop or another PC in the same
network.
"""

import json
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from urllib import request, error

SERVER_URL = os.environ.get("GREENHOUSE_SERVER_URL", "http://localhost:4100").rstrip("/")


def api_get(path):
    with request.urlopen(SERVER_URL + path, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def api_post(path, payload=None):
    body = json.dumps(payload or {}).encode("utf-8")
    req = request.Request(
        SERVER_URL + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


class GreenhouseGui(tk.Tk):# GreenhouseGui 클래스 정의, tk.Tk를 상속하여 GUI 애플리케이션의 메인 윈도우 역할을 함
    def __init__(self):
        super().__init__()
        self.title("STREW VISION")
        self.geometry("1280x760")
        self.minsize(1050, 660)
        self.configure(bg="#060912")
        self.dashboard = None
        self.details = None
        self.ai_enabled = False
        self._build_style()
        self._build_ui()
        self.refresh_all()

    def _build_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#060912")
        style.configure("Panel.TFrame", background="#0e1726", relief="flat")
        style.configure("TLabel", background="#060912", foreground="#e9f7ff")
        style.configure("Muted.TLabel", background="#060912", foreground="#8ba0b8")
        style.configure("Panel.TLabel", background="#0e1726", foreground="#e9f7ff")
        style.configure("Metric.TLabel", background="#0e1726", foreground="#35d5ff", font=("Arial", 20, "bold"))
        style.configure("TButton", padding=8, background="#13243a", foreground="#e9f7ff")
        style.configure("Accent.TButton", background="#35d5ff", foreground="#06101d")
        style.configure("Danger.TButton", background="#ff5d73", foreground="#ffffff")
        style.configure("Treeview", background="#0e1726", foreground="#e9f7ff", fieldbackground="#0e1726", rowheight=28, borderwidth=0)
        style.configure("Treeview.Heading", background="#13243a", foreground="#b8c8da")

    def _build_ui(self):
        header = ttk.Frame(self)
        header.pack(fill="x", padx=18, pady=(16, 8))
        ttk.Label(header, text="Jetson Greenhouse Control", font=("Arial", 22, "bold")).pack(side="left")
        self.status_label = ttk.Label(header, text=f"Server: {SERVER_URL}", style="Muted.TLabel")
        self.status_label.pack(side="left", padx=18)
        ttk.Button(header, text="Refresh", command=self.refresh_all).pack(side="right")
        self.ai_button = ttk.Button(header, text="AI Mode OFF", style="Danger.TButton", command=self.toggle_ai)
        self.ai_button.pack(side="right", padx=8)

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.main_tab = ttk.Frame(self.tabs)
        self.alert_tab = ttk.Frame(self.tabs)
        self.detail_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.main_tab, text="Main")
        self.tabs.add(self.alert_tab, text="Alerts / Approval")
        self.tabs.add(self.detail_tab, text="Details")
        self._build_main_tab()
        self._build_alert_tab()
        self._build_detail_tab()

    def _panel(self, parent):
        return ttk.Frame(parent, style="Panel.TFrame", padding=14)

    def _build_main_tab(self):
        metrics = ttk.Frame(self.main_tab)
        metrics.pack(fill="x", padx=8, pady=8)
        self.metric_labels = {}
        for key in ["Cells", "Warnings", "Pending", "Avg Temp", "Avg Humidity"]:
            panel = self._panel(metrics)
            panel.pack(side="left", fill="x", expand=True, padx=5)
            ttk.Label(panel, text=key, style="Panel.TLabel").pack(anchor="w")
            value = ttk.Label(panel, text="-", style="Metric.TLabel")
            value.pack(anchor="w", pady=(8, 0))
            self.metric_labels[key] = value

        body = ttk.Frame(self.main_tab)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        self.cell_tree = self._tree(body, ["cell", "risk", "temp", "humidity", "sap", "disease", "robot"])
        self.cell_tree.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.event_tree = self._tree(body, ["time", "type", "message"])
        self.event_tree.pack(side="left", fill="both", expand=True, padx=(8, 0))

    def _build_alert_tab(self):
        top = ttk.Frame(self.alert_tab)
        top.pack(fill="both", expand=True, padx=8, pady=8)
        self.approval_tree = self._tree(top, ["id", "cell", "ai", "probability", "message"])
        self.approval_tree.pack(fill="both", expand=True, side="left", padx=(0, 8))
        actions = self._panel(top)
        actions.pack(fill="y", side="left")
        ttk.Label(actions, text="Selected approval", style="Panel.TLabel", font=("Arial", 13, "bold")).pack(anchor="w")
        ttk.Button(actions, text="Approve", style="Accent.TButton", command=self.approve_selected).pack(fill="x", pady=(18, 8))
        ttk.Button(actions, text="Reject", style="Danger.TButton", command=self.reject_selected).pack(fill="x")
        ttk.Label(actions, text="문제 셀과 승인 대기 작업을 검토합니다.", style="Panel.TLabel", wraplength=220).pack(anchor="w", pady=(24, 0))

    def _build_detail_tab(self):
        selector = ttk.Frame(self.detail_tab)
        selector.pack(fill="x", padx=8, pady=8)
        self.detail_kind = tk.StringVar(value="sensorLogs")
        for label, value in [("Sensor", "sensorLogs"), ("AI", "aiReadings"), ("Tasks", "tasks"), ("Feedback", "feedback"), ("Events", "events")]:
            ttk.Radiobutton(selector, text=label, variable=self.detail_kind, value=value, command=self.render_details).pack(side="left", padx=5)
        self.detail_tree = self._tree(self.detail_tab, [])
        self.detail_tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _tree(self, parent, columns):
        frame = ttk.Frame(parent)
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        y_scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.tree = tree
        self._set_tree_columns(tree, columns)
        return frame

    def _set_tree_columns(self, tree, columns):
        tree.configure(columns=columns)
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=130, anchor="w", stretch=True)

    def refresh_all(self):
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            dashboard = api_get("/api/dashboard")
            details = api_get("/api/details")
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            self.after(0, lambda: self.status_label.configure(text=f"API error: {exc}"))
            return
        self.after(0, lambda: self._apply_data(dashboard, details))

    def _apply_data(self, dashboard, details):
        self.dashboard = dashboard
        self.details = details
        self.ai_enabled = bool(dashboard.get("aiMode", {}).get("enabled"))
        self.ai_button.configure(text="AI Mode ON" if self.ai_enabled else "AI Mode OFF", style="Accent.TButton" if self.ai_enabled else "Danger.TButton")
        self.status_label.configure(text=f"Updated: {dashboard.get('generatedAt', '-')}")
        summary = dashboard.get("summary", {})
        values = {
            "Cells": summary.get("cellCount", 0),
            "Warnings": summary.get("warningCount", 0),
            "Pending": summary.get("pendingApprovalCount", 0),
            "Avg Temp": f"{summary.get('avgTemperature', 0)}C",
            "Avg Humidity": f"{summary.get('avgHumidity', 0)}%",
        }
        for key, value in values.items():
            self.metric_labels[key].configure(text=value)
        self.render_main()
        self.render_alerts()
        self.render_details()

    def render_main(self):
        tree = self.cell_tree.tree
        tree.delete(*tree.get_children())
        for panel in self.dashboard.get("panels", []):
            tree.insert("", "end", values=(panel.get("cellName"), panel.get("riskLevel"), panel.get("temperature"), panel.get("humidity"), panel.get("sapAmountMl"), panel.get("diseaseProbability"), f"{panel.get('stateMachine')} {panel.get('progressRate')}%"))
        event_tree = self.event_tree.tree
        event_tree.delete(*event_tree.get_children())
        for event in self.dashboard.get("events", [])[:30]:
            event_tree.insert("", "end", values=(event.get("event_time"), event.get("event_type"), event.get("message")))

    def render_alerts(self):
        tree = self.approval_tree.tree
        tree.delete(*tree.get_children())
        for approval in self.dashboard.get("pendingApprovals", []):
            tree.insert("", "end", iid=str(approval.get("id")), values=(approval.get("id"), approval.get("cell_id"), approval.get("ai_mode"), approval.get("disease_probability"), approval.get("review_message")))

    def render_details(self):
        if not self.details:
            return
        kind = self.detail_kind.get()
        rows = self.details.get(kind, [])
        columns = list(rows[0].keys()) if rows else ["message"]
        tree = self.detail_tree.tree
        self._set_tree_columns(tree, columns)
        tree.delete(*tree.get_children())
        for row in rows[:300]:
            tree.insert("", "end", values=[row.get(col, "") for col in columns])

    def selected_approval_id(self):
        selected = self.approval_tree.tree.selection()
        if not selected:
            messagebox.showinfo("Approval", "승인/거절할 항목을 선택하세요.")
            return None
        return selected[0]

    def approve_selected(self):
        approval_id = self.selected_approval_id()
        if approval_id:
            api_post(f"/api/approval/{approval_id}/approve")
            self.refresh_all()

    def reject_selected(self):
        approval_id = self.selected_approval_id()
        if approval_id:
            api_post(f"/api/approval/{approval_id}/reject")
            self.refresh_all()

    def toggle_ai(self):
        try:
            api_post("/api/ai-mode", {"enabled": not self.ai_enabled, "modeName": "AUTO_MONITOR"})
            self.refresh_all()
        except Exception as exc:
            messagebox.showerror("AI Mode", str(exc))


if __name__ == "__main__":
    app = GreenhouseGui()
    app.mainloop()
