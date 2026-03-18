import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FadeIn, ScaleIn, CountUp } from './AnimatedList';

// Mock framer-motion to avoid animation complexity in tests
vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, className, style, ...rest }: any) => (
      <div className={className} style={style} data-testid="motion-div">{children}</div>
    ),
  },
  AnimatePresence: ({ children }: any) => <>{children}</>,
}));

describe('FadeIn', () => {
  it('renders children', () => {
    render(<FadeIn><span>Hello</span></FadeIn>);
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('applies className', () => {
    render(<FadeIn className="my-class"><span>Content</span></FadeIn>);
    const wrapper = screen.getByTestId('motion-div');
    expect(wrapper).toHaveClass('my-class');
  });

  it('applies inline style', () => {
    render(<FadeIn style={{ maxHeight: 100 }}><span>Content</span></FadeIn>);
    const wrapper = screen.getByTestId('motion-div');
    expect(wrapper.style.maxHeight).toBe('100px');
  });
});

describe('ScaleIn', () => {
  it('renders children', () => {
    render(<ScaleIn><div>Scale content</div></ScaleIn>);
    expect(screen.getByText('Scale content')).toBeInTheDocument();
  });

  it('applies className', () => {
    render(<ScaleIn className="scale-class"><div>X</div></ScaleIn>);
    expect(screen.getByTestId('motion-div')).toHaveClass('scale-class');
  });
});

describe('CountUp', () => {
  it('renders a span element', () => {
    const { container } = render(<CountUp end={100} />);
    const span = container.querySelector('span');
    expect(span).toBeInTheDocument();
  });

  it('applies className', () => {
    const { container } = render(<CountUp end={50} className="count-class" />);
    const span = container.querySelector('span');
    expect(span).toHaveClass('count-class');
  });

  it('renders 0 when end is 0', () => {
    render(<CountUp end={0} />);
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  it('uses custom format function', () => {
    render(<CountUp end={0} format={(n) => `${n} items`} />);
    expect(screen.getByText('0 items')).toBeInTheDocument();
  });
});
