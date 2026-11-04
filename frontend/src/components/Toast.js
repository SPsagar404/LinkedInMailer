"use client";

import { useEffect, useState } from "react";

export default function Toast({ toasts, onRemove }) {
  return (
    <div className="toast-container">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onRemove={onRemove} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onRemove }) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setVisible(false);
      setTimeout(() => onRemove(toast.id), 300);
    }, toast.duration || 4000);

    return () => clearTimeout(timer);
  }, [toast, onRemove]);

  const typeClass = `toast-${toast.type || "info"}`;
  const icon = {
    success: "✅",
    error: "❌",
    info: "ℹ️",
    warning: "⚠️",
  }[toast.type || "info"];

  return (
    <div
      className={`toast ${typeClass}`}
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? "translateX(0)" : "translateX(100px)",
        transition: "all 300ms ease",
      }}
    >
      <span>{icon}</span>
      <span className="toast-message">{toast.message}</span>
      <button className="toast-close" onClick={() => onRemove(toast.id)}>
        ✕
      </button>
    </div>
  );
}
