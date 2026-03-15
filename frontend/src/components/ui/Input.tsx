import { type InputHTMLAttributes, type ReactNode, forwardRef, useId } from 'react';

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'prefix'> {
  prefix?: ReactNode;
  suffix?: ReactNode;
  error?: string;
  label?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(({
  prefix,
  suffix,
  error,
  label,
  className = '',
  id: propId,
  ...props
}, ref) => {
  const autoId = useId();
  const inputId = propId || autoId;
  const errorId = error ? `${inputId}-error` : undefined;

  return (
    <div className="w-full">
      {label && <label htmlFor={inputId} className="block text-xs font-medium text-text-muted mb-1.5">{label}</label>}
      <div className={`
        flex items-center gap-2 bg-deep-base border rounded-[10px] px-3 py-2
        transition-all duration-200
        ${error ? 'border-red-500/50 focus-within:border-red-500 focus-within:shadow-[0_0_0_3px_rgba(239,68,68,0.1)]' : 'border-glass-border focus-within:border-emerald-accent/40 focus-within:shadow-[0_0_0_3px_rgba(16,185,129,0.1)]'}
        ${className}
      `.trim()}>
        {prefix && <span className="text-text-dim text-sm shrink-0" aria-hidden="true">{prefix}</span>}
        <input
          ref={ref}
          id={inputId}
          className="flex-1 bg-transparent outline-none text-sm text-text-bright placeholder:text-text-dim min-w-0"
          aria-invalid={error ? true : undefined}
          aria-describedby={errorId}
          {...props}
        />
        {suffix && <span className="text-text-dim text-sm shrink-0" aria-hidden="true">{suffix}</span>}
      </div>
      {error && <p id={errorId} className="text-xs text-red-400 mt-1" role="alert">{error}</p>}
    </div>
  );
});

Input.displayName = 'Input';

interface TextAreaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
}

export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(({
  label,
  error,
  className = '',
  id: propId,
  ...props
}, ref) => {
  const autoId = useId();
  const textareaId = propId || autoId;
  const errorId = error ? `${textareaId}-error` : undefined;

  return (
    <div className="w-full">
      {label && <label htmlFor={textareaId} className="block text-xs font-medium text-text-muted mb-1.5">{label}</label>}
      <textarea
        ref={ref}
        id={textareaId}
        className={`
          w-full bg-deep-base border border-glass-border rounded-[10px] px-3 py-2
          text-sm text-text-bright placeholder:text-text-dim outline-none resize-y
          transition-all duration-200
          focus:border-emerald-accent/40 focus:shadow-[0_0_0_3px_rgba(16,185,129,0.1)]
          ${className}
        `.trim()}
        aria-invalid={error ? true : undefined}
        aria-describedby={errorId}
        {...props}
      />
      {error && <p id={errorId} className="text-xs text-red-400 mt-1" role="alert">{error}</p>}
    </div>
  );
});

TextArea.displayName = 'TextArea';

interface NumberInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'onChange'> {
  label?: string;
  error?: string;
  value?: number;
  onChange?: (value: number | null) => void;
  min?: number;
  max?: number;
}

export const NumberInput = forwardRef<HTMLInputElement, NumberInputProps>(({
  label,
  error,
  value,
  onChange,
  className = '',
  id: propId,
  ...props
}, ref) => {
  const autoId = useId();
  const inputId = propId || autoId;
  const errorId = error ? `${inputId}-error` : undefined;

  return (
    <div className="w-full">
      {label && <label htmlFor={inputId} className="block text-xs font-medium text-text-muted mb-1.5">{label}</label>}
      <input
        ref={ref}
        id={inputId}
        type="number"
        value={value ?? ''}
        onChange={(e) => {
          const val = e.target.value === '' ? null : Number(e.target.value);
          onChange?.(val);
        }}
        className={`
          w-full bg-deep-base border border-glass-border rounded-[10px] px-3 py-2
          text-sm text-text-bright placeholder:text-text-dim outline-none
          transition-all duration-200
          focus:border-emerald-accent/40 focus:shadow-[0_0_0_3px_rgba(16,185,129,0.1)]
          [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none
          ${className}
        `.trim()}
        aria-invalid={error ? true : undefined}
        aria-describedby={errorId}
        {...props}
      />
      {error && <p id={errorId} className="text-xs text-red-400 mt-1" role="alert">{error}</p>}
    </div>
  );
});

NumberInput.displayName = 'NumberInput';
