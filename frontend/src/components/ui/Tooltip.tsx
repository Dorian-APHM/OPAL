import { useState, useRef, useId, useEffect, cloneElement, type ReactNode, type ReactElement, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';

interface TooltipProps {
  title: ReactNode;
  children: ReactElement;
  placement?: 'top' | 'bottom' | 'left' | 'right';
}

const GAP = 8;

export function Tooltip({ title, children, placement = 'top' }: TooltipProps) {
  // Rendered in a portal with fixed positioning so the tip is never clipped
  // by overflow ancestors (Card rounded corners, Table overflow-auto, ...).
  const [pos, setPos] = useState<CSSProperties | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const tipId = useId();

  const visible = pos !== null;

  const show = () => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    switch (placement) {
      case 'bottom':
        setPos({ left: rect.left + rect.width / 2, top: rect.bottom + GAP, transform: 'translateX(-50%)' });
        break;
      case 'left':
        setPos({ left: rect.left - GAP, top: rect.top + rect.height / 2, transform: 'translate(-100%, -50%)' });
        break;
      case 'right':
        setPos({ left: rect.right + GAP, top: rect.top + rect.height / 2, transform: 'translateY(-50%)' });
        break;
      default: // top
        setPos({ left: rect.left + rect.width / 2, top: rect.top - GAP, transform: 'translate(-50%, -100%)' });
    }
  };
  const hide = () => setPos(null);

  // The position is fixed (viewport-relative): hide on any scroll so the tip
  // never floats away from its trigger. Capture phase catches inner containers.
  useEffect(() => {
    if (!visible) return;
    window.addEventListener('scroll', hide, true);
    return () => window.removeEventListener('scroll', hide, true);
  }, [visible]);

  if (!title) return children;

  return (
    <div
      ref={ref}
      className="inline-flex"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {/* Link the trigger to the tooltip for screen readers when visible. */}
      {cloneElement(children, visible ? { 'aria-describedby': tipId } : {})}
      {visible && createPortal(
        <div className="fixed z-[1100] pointer-events-none" style={pos}>
          <div
            id={tipId}
            role="tooltip"
            className="px-2.5 py-1.5 rounded-lg bg-surface-light text-xs text-text-bright shadow-[0_4px_16px_rgba(0,0,0,0.3)] max-w-xs whitespace-normal break-words border border-glass-border"
          >
            {title}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
