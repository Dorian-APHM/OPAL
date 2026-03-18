/**
 * AnimatedList — staggered entrance animation for lists of items.
 * Uses Framer Motion for smooth mount/unmount with cascading delays.
 */
import { type ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

interface AnimatedListProps {
  children: ReactNode[];
  /** Stagger delay between each item in seconds */
  stagger?: number;
  className?: string;
}

const itemVariants = {
  hidden: { opacity: 0, y: 12 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.05, duration: 0.25, ease: 'easeOut' },
  }),
  exit: { opacity: 0, y: -8, transition: { duration: 0.15 } },
};

/** Stable variant factory — avoids recreating objects on every render/item. */
const makeItemVariants = (stagger: number) => ({
  hidden: { opacity: 0, y: 12 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * stagger, duration: 0.25, ease: 'easeOut' as const },
  }),
  exit: { opacity: 0, y: -8, transition: { duration: 0.15 } },
});

// Default variants for the common stagger=0.05 case (zero-alloc hot path)
const defaultVariants = makeItemVariants(0.05);

export function AnimatedList({ children, stagger = 0.05, className = '' }: AnimatedListProps) {
  const variants = stagger === 0.05 ? defaultVariants : makeItemVariants(stagger);
  return (
    <div className={className}>
      <AnimatePresence mode="popLayout">
        {children.map((child, i) => (
          <motion.div
            key={(child as any)?.key ?? i}
            custom={i}
            variants={variants}
            initial="hidden"
            animate="visible"
            exit="exit"
          >
            {child}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

/**
 * FadeIn — simple fade + slide-up wrapper for any content.
 */
interface FadeInProps {
  children: ReactNode;
  delay?: number;
  duration?: number;
  direction?: 'up' | 'down' | 'left' | 'right' | 'none';
  className?: string;
  style?: React.CSSProperties;
}

const directionMap = {
  up: { y: 16 },
  down: { y: -16 },
  left: { x: 16 },
  right: { x: -16 },
  none: {},
};

export function FadeIn({ children, delay = 0, duration = 0.3, direction = 'up', className = '', style }: FadeInProps) {
  return (
    <motion.div
      initial={{ opacity: 0, ...directionMap[direction] }}
      animate={{ opacity: 1, x: 0, y: 0 }}
      transition={{ delay, duration, ease: 'easeOut' }}
      className={className}
      style={style}
    >
      {children}
    </motion.div>
  );
}

/**
 * ScaleIn — pop-in effect for cards, modals, stat numbers.
 */
interface ScaleInProps {
  children: ReactNode;
  delay?: number;
  className?: string;
}

export function ScaleIn({ children, delay = 0, className = '' }: ScaleInProps) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.92 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay, duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

/**
 * CountUp — animates a number from 0 to target value.
 */
import { useState, useEffect, useRef } from 'react';

interface CountUpProps {
  end: number;
  duration?: number;
  format?: (n: number) => string;
  className?: string;
}

export function CountUp({ end, duration = 800, format, className = '' }: CountUpProps) {
  const [value, setValue] = useState(0);
  const rafRef = useRef<number>(0);
  const startTimeRef = useRef<number>(0);

  useEffect(() => {
    if (end === 0) { setValue(0); return; }
    startTimeRef.current = performance.now();
    const animate = (now: number) => {
      const elapsed = now - startTimeRef.current;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.round(eased * end));
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate);
      }
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [end, duration]);

  const display = format ? format(value) : value.toLocaleString();
  return <span className={className}>{display}</span>;
}
