import { useEffect, useRef, type KeyboardEvent, type ReactNode, type RefObject } from "react";

/**
 * Hộp xác nhận tại chỗ (role=alertdialog): mở ra thì focus vào nút đầu, Tab/Shift+Tab chỉ đi vòng trong hộp,
 * Esc = Huỷ; đóng thì trả focus về nút đã mở hộp (`returnFocus`).
 */
export function ConfirmBox({ title, children, confirmLabel, onConfirm, onCancel, returnFocus, busy }: {
  title: string; children?: ReactNode; confirmLabel: string; onConfirm: () => void; onCancel: () => void;
  returnFocus?: RefObject<HTMLElement | null>; busy?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("button")?.focus();
    const back = returnFocus?.current;
    return () => { back?.focus(); };
  }, [returnFocus]);
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") { e.preventDefault(); onCancel(); return; }
    if (e.key !== "Tab" || !ref.current) return;
    const items = [...ref.current.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], input, select, textarea")];
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  return (
    <div ref={ref} className="error-box drop" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title"
         aria-describedby={children ? "confirm-detail" : undefined} onKeyDown={onKeyDown} style={{ marginTop: 12 }}>
      <strong id="confirm-title">{title}</strong>
      {children && <span id="confirm-detail" className="detail">{children}</span>}
      <div className="inline">
        <button type="button" className="btn-ghost sm pill danger-solid" disabled={busy} onClick={onConfirm}>{confirmLabel}</button>
        <button type="button" className="btn-ghost sm pill" onClick={onCancel}>Huỷ</button>
      </div>
    </div>
  );
}
