import { type ReactNode } from 'react';
import { X } from 'lucide-react';

type TagColor = 'emerald' | 'blue' | 'red' | 'orange' | 'purple' | 'cyan' | 'yellow' | 'magenta' | 'green' | 'default' | 'teal';

const colorMap: Record<TagColor, string> = {
  emerald: 'bg-emerald-500/12 text-emerald-400 border-emerald-500/25',
  green: 'bg-emerald-500/12 text-emerald-400 border-emerald-500/25',
  blue: 'bg-blue-500/12 text-blue-400 border-blue-500/25',
  red: 'bg-red-500/12 text-red-400 border-red-500/25',
  orange: 'bg-orange-500/12 text-orange-400 border-orange-500/25',
  purple: 'bg-purple-500/12 text-purple-400 border-purple-500/25',
  cyan: 'bg-cyan-500/12 text-cyan-400 border-cyan-500/25',
  yellow: 'bg-yellow-500/12 text-yellow-400 border-yellow-500/25',
  magenta: 'bg-pink-500/12 text-pink-400 border-pink-500/25',
  teal: 'bg-teal-500/12 text-teal-400 border-teal-500/25',
  default: 'bg-slate-500/12 text-slate-400 border-slate-500/25',
};

interface TagProps {
  children: ReactNode;
  color?: TagColor;
  closable?: boolean;
  onClose?: () => void;
  className?: string;
  style?: React.CSSProperties;
}

export function Tag({ children, color = 'default', closable, onClose, className = '', style }: TagProps) {
  return (
    <span
      className={`
        inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-xs font-medium
        ${colorMap[color] || colorMap.default}
        ${className}
      `.trim()}
      style={style}
    >
      {children}
      {closable && (
        <button onClick={onClose} className="hover:opacity-80 cursor-pointer bg-transparent border-none text-current p-0">
          <X className="h-3 w-3" />
        </button>
      )}
    </span>
  );
}
