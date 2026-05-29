import { useState, useRef, useId, cloneElement, type ReactNode, type ReactElement } from 'react';

interface TooltipProps {
  title: ReactNode;
  children: ReactElement;
  placement?: 'top' | 'bottom' | 'left' | 'right';
}

export function Tooltip({ title, children, placement = 'top' }: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const tipId = useId();

  if (!title) return children;

  const positionClasses = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  };

  const show = () => setVisible(true);
  const hide = () => setVisible(false);

  return (
    <div
      ref={ref}
      className="relative inline-flex"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {/* Link the trigger to the tooltip for screen readers when visible. */}
      {cloneElement(children, visible ? { 'aria-describedby': tipId } : {})}
      {visible && (
        <div className={`absolute z-[1100] ${positionClasses[placement]} pointer-events-none`}>
          <div
            id={tipId}
            role="tooltip"
            className="px-2.5 py-1.5 rounded-lg bg-surface-light text-xs text-text-bright shadow-[0_4px_16px_rgba(0,0,0,0.3)] max-w-xs whitespace-normal break-words border border-glass-border"
          >
            {title}
          </div>
        </div>
      )}
    </div>
  );
}
