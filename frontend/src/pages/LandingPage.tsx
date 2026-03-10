import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ShieldCheck,
  Users,
  GitCompareArrows,
  Network,
  ExternalLink,
  Menu,
  X,
  ChevronRight,
  Sparkles,
  Activity,
  Database,
  BarChart3,
} from 'lucide-react';

// ── Animation Variants ──────────────────────────────────────
const fadeUp = {
  hidden: { opacity: 0, y: 30 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.1, duration: 0.6, ease: [0.25, 0.46, 0.45, 0.94] as const },
  }),
};

const stagger = {
  visible: { transition: { staggerChildren: 0.12 } },
};

const scaleIn = {
  hidden: { opacity: 0, scale: 0.9 },
  visible: { opacity: 1, scale: 1, transition: { duration: 0.7, ease: 'easeOut' as const } },
};

// ── Nav Links ───────────────────────────────────────────────
const NAV_LINKS = [
  { label: 'Quality', href: '#features' },
  { label: 'Cohorts', href: '#features' },
  { label: 'Mapping', href: '#features' },
  { label: 'Concepts', href: '#features' },
  { label: 'Pricing', href: '#cta' },
];

// ── Feature Cards Data ──────────────────────────────────────
const FEATURES = [
  {
    icon: ShieldCheck,
    title: 'Soft Data Quality Check',
    description:
      'Automated Achilles-like quality metrics with temporal snapshots and versioned comparison across your OMOP CDM.',
    gradient: 'from-emerald-accent to-teal-accent',
  },
  {
    icon: Users,
    title: 'Soft Cohort Creator',
    description:
      'Visual cohort builder translating JSON criteria to optimized SQL with real-time attrition analysis and patient sampling.',
    gradient: 'from-teal-accent to-emerald-light',
  },
  {
    icon: GitCompareArrows,
    title: 'Semantic Mapping Lab',
    description:
      '5-step mapping workflow with 4 AI suggestion strategies: exact, relationship-based, fuzzy text, and contextual matching.',
    gradient: 'from-emerald-light to-emerald-accent',
  },
  {
    icon: Network,
    title: 'Lineage Explorer',
    description:
      'Navigate concept hierarchies, explore source values, and trace relationships across your entire OMOP vocabulary.',
    gradient: 'from-emerald-accent to-teal-accent',
  },
];

// ── Stats ───────────────────────────────────────────────────
const STATS = [
  { label: 'OMOP Domains', value: '30+', icon: Database },
  { label: 'Quality Metrics', value: '150+', icon: BarChart3 },
  { label: 'Mapping Strategies', value: '4', icon: Sparkles },
  { label: 'Real-time Analysis', value: '24/7', icon: Activity },
];

// ── Glass Navigation ────────────────────────────────────────
function GlassNav() {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <motion.nav
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="glass-nav fixed top-0 left-0 right-0 z-50 px-6 py-4"
    >
      <div className="mx-auto flex max-w-7xl items-center justify-between">
        {/* Logo */}
        <a href="/" className="flex items-center gap-3 no-underline">
          <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-accent/10">
            <div className="h-5 w-5 rounded-full border-2 border-emerald-accent" />
            <div className="absolute h-2 w-2 rounded-full bg-emerald-accent cyber-glow" />
          </div>
          <span className="text-xl font-bold text-text-bright tracking-tight">OPAL</span>
        </a>

        {/* Desktop Links */}
        <div className="hidden items-center gap-8 md:flex">
          {NAV_LINKS.map((link) => (
            <a
              key={link.label}
              href={link.href}
              className="text-sm font-medium text-text-muted transition-colors duration-200 hover:text-emerald-accent no-underline"
            >
              {link.label}
            </a>
          ))}
        </div>

        {/* CTA Button */}
        <div className="hidden md:block">
          <a
            href="#cta"
            className="inline-flex items-center gap-2 rounded-xl border border-emerald-accent/30 bg-emerald-accent/10 px-5 py-2.5 text-sm font-semibold text-emerald-accent transition-all duration-300 hover:bg-emerald-accent/20 hover:shadow-[0_0_20px_rgba(16,185,129,0.2)] no-underline"
          >
            <ExternalLink className="h-4 w-4" />
            Request Demo
          </a>
        </div>

        {/* Mobile Toggle */}
        <button
          onClick={() => setMobileOpen(!mobileOpen)}
          className="text-text-muted md:hidden bg-transparent border-none cursor-pointer"
        >
          {mobileOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
        </button>
      </div>

      {/* Mobile Menu */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden md:hidden"
          >
            <div className="flex flex-col gap-4 pb-4 pt-6">
              {NAV_LINKS.map((link) => (
                <a
                  key={link.label}
                  href={link.href}
                  onClick={() => setMobileOpen(false)}
                  className="text-sm font-medium text-text-muted transition-colors hover:text-emerald-accent no-underline"
                >
                  {link.label}
                </a>
              ))}
              <a
                href="#cta"
                className="btn-emerald mt-2 inline-flex items-center justify-center gap-2 text-sm no-underline"
              >
                <ExternalLink className="h-4 w-4" />
                Request Demo
              </a>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.nav>
  );
}

// ── Hero Section ────────────────────────────────────────────
function HeroSection() {
  return (
    <section className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-6 pt-24 pb-16">
      {/* Background Grid Effect */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            'linear-gradient(rgba(16,185,129,0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(16,185,129,0.3) 1px, transparent 1px)',
          backgroundSize: '60px 60px',
        }}
      />

      {/* Radial Glow */}
      <div className="pointer-events-none absolute top-1/4 left-1/2 h-[600px] w-[800px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-emerald-glow opacity-30 blur-[100px]" />

      <motion.div
        variants={stagger}
        initial="hidden"
        animate="visible"
        className="relative z-10 mx-auto max-w-4xl text-center"
      >
        <motion.div variants={fadeUp} custom={0} className="mb-6">
          <span className="inline-flex items-center gap-2 rounded-full border border-emerald-accent/20 bg-emerald-accent/10 px-4 py-1.5 text-xs font-medium text-emerald-accent">
            <Sparkles className="h-3.5 w-3.5" />
            OMOP CDM Analytics Platform
          </span>
        </motion.div>

        <motion.h1
          variants={fadeUp}
          custom={1}
          className="gradient-text mb-6 text-5xl font-bold leading-tight tracking-tight md:text-7xl"
        >
          Unify & Analyze
          <br />
          Your Healthcare Data
        </motion.h1>

        <motion.p
          variants={fadeUp}
          custom={2}
          className="mx-auto mb-10 max-w-2xl text-lg text-text-muted md:text-xl"
        >
          Advanced OMOP Analytics with a Seamless, Soft-Dark UI.
          <br className="hidden md:block" />
          Quality checks, cohort building, and semantic mapping — all in one platform.
        </motion.p>

        <motion.div variants={fadeUp} custom={3} className="flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
          <a
            href="#cta"
            className="btn-emerald inline-flex items-center gap-2 text-base no-underline"
          >
            Get Started
            <ChevronRight className="h-5 w-5" />
          </a>
          <a
            href="#features"
            className="inline-flex items-center gap-2 rounded-xl border border-border-subtle bg-surface/50 px-7 py-3 text-sm font-medium text-text-muted transition-all duration-300 hover:border-emerald-accent/20 hover:text-text-bright no-underline"
          >
            Explore Features
          </a>
        </motion.div>
      </motion.div>

      {/* Dashboard Preview */}
      <motion.div
        variants={scaleIn}
        initial="hidden"
        animate="visible"
        className="dashboard-glow relative z-10 mx-auto mt-16 w-full max-w-5xl"
      >
        <div className="neumorphic-card overflow-hidden p-1">
          <DashboardPreview />
        </div>
      </motion.div>
    </section>
  );
}

// ── Dashboard Preview (Simulated) ───────────────────────────
function DashboardPreview() {
  return (
    <div className="rounded-[20px] bg-deep-base p-4 md:p-6">
      {/* Top Bar */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-accent/10">
            <div className="h-3.5 w-3.5 rounded-full border-[1.5px] border-emerald-accent" />
          </div>
          <span className="text-sm font-semibold text-text-bright">OPAL</span>
        </div>
        <div className="text-xs font-medium text-text-dim">Dashboard</div>
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-emerald-accent cyber-glow" />
          <div className="h-6 w-6 rounded-full bg-surface-light" />
        </div>
      </div>

      <div className="flex gap-4">
        {/* Sidebar */}
        <div className="hidden w-36 flex-col gap-2 md:flex">
          {['Home', 'Cohorts', 'Commands', 'Mapping', 'Concepts', 'Settings'].map((item, i) => (
            <div
              key={item}
              className={`rounded-lg px-3 py-1.5 text-xs ${
                i === 0
                  ? 'bg-emerald-accent/10 text-emerald-accent font-medium'
                  : 'text-text-dim'
              }`}
            >
              {item}
            </div>
          ))}
        </div>

        {/* Main Content */}
        <div className="flex-1 space-y-4">
          {/* Metric Cards Row */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              { label: 'Dynamic quality', value: '25%', color: 'emerald' },
              { label: 'CHM Status', value: '100%', color: 'emerald' },
              { label: 'CDO Grilles', value: '56%', color: 'emerald' },
              { label: 'Patient Visitors', value: '—', color: 'teal' },
            ].map((metric) => (
              <div key={metric.label} className="rounded-xl bg-surface p-3">
                <div className="mb-2 text-[10px] text-text-dim">{metric.label}</div>
                <div className="flex items-center justify-center">
                  <div className="relative flex h-12 w-12 items-center justify-center">
                    <svg className="h-12 w-12 -rotate-90" viewBox="0 0 48 48">
                      <circle
                        cx="24"
                        cy="24"
                        r="20"
                        fill="none"
                        stroke="rgba(16,185,129,0.1)"
                        strokeWidth="3"
                      />
                      <circle
                        cx="24"
                        cy="24"
                        r="20"
                        fill="none"
                        stroke="#10B981"
                        strokeWidth="3"
                        strokeDasharray={`${2 * Math.PI * 20}`}
                        strokeDashoffset={`${2 * Math.PI * 20 * (1 - parseInt(metric.value) / 100 || 0)}`}
                        strokeLinecap="round"
                        className="transition-all duration-1000"
                      />
                    </svg>
                    <span className="absolute text-[10px] font-semibold text-emerald-accent">
                      {metric.value}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Chart Area */}
          <div className="rounded-xl bg-surface p-4">
            <div className="flex items-end gap-1 h-20">
              {[40, 65, 45, 80, 55, 70, 60, 75, 50, 85, 65, 90].map((h, i) => (
                <div
                  key={i}
                  className="flex-1 rounded-t bg-gradient-to-t from-emerald-accent/30 to-emerald-accent/80"
                  style={{ height: `${h}%` }}
                />
              ))}
            </div>
            <div className="mt-2 flex justify-between text-[8px] text-text-dim">
              {['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].map((m) => (
                <span key={m}>{m}</span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Stats Section ───────────────────────────────────────────
function StatsSection() {
  return (
    <section className="relative py-16 px-6">
      <div className="mx-auto grid max-w-5xl grid-cols-2 gap-6 md:grid-cols-4">
        {STATS.map((stat, i) => (
          <motion.div
            key={stat.label}
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: '-50px' }}
            custom={i}
            className="flex flex-col items-center gap-2 rounded-2xl border border-border-subtle bg-surface/50 p-6 text-center"
          >
            <stat.icon className="h-5 w-5 text-emerald-accent mb-1" />
            <div className="text-3xl font-bold text-text-bright">{stat.value}</div>
            <div className="text-xs text-text-muted">{stat.label}</div>
          </motion.div>
        ))}
      </div>
    </section>
  );
}

// ── Bento Grid Features ─────────────────────────────────────
function FeaturesSection() {
  return (
    <section id="features" className="relative py-20 px-6">
      <div className="mx-auto max-w-6xl">
        <motion.div
          variants={stagger}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-80px' }}
          className="mb-16 text-center"
        >
          <motion.h2
            variants={fadeUp}
            custom={0}
            className="gradient-text mb-4 text-3xl font-bold md:text-5xl"
          >
            Everything You Need
          </motion.h2>
          <motion.p variants={fadeUp} custom={1} className="mx-auto max-w-xl text-text-muted">
            A complete suite of tools for OMOP CDM analytics, built with precision and care.
          </motion.p>
        </motion.div>

        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map((feature, i) => (
            <motion.div
              key={feature.title}
              variants={fadeUp}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true, margin: '-50px' }}
              custom={i}
              whileHover={{ y: -4 }}
              className="neumorphic-card group relative flex flex-col p-8"
            >
              {/* Icon with Halo */}
              <div className="icon-halo relative mb-6 inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-emerald-accent/10">
                <feature.icon className="h-8 w-8 text-emerald-accent transition-all duration-300 group-hover:cyber-glow" />
              </div>

              <h3 className="mb-3 text-lg font-semibold text-text-bright">{feature.title}</h3>
              <p className="text-sm leading-relaxed text-text-muted">{feature.description}</p>

              {/* Bottom Gradient Line */}
              <div className="mt-auto pt-6">
                <div className={`h-0.5 w-full rounded-full bg-gradient-to-r ${feature.gradient} opacity-20 transition-opacity duration-300 group-hover:opacity-60`} />
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Testimonial Section ─────────────────────────────────────
function TestimonialSection() {
  return (
    <section className="relative py-20 px-6">
      <div className="mx-auto max-w-4xl">
        <div className="grid gap-8 md:grid-cols-2 items-center">
          {/* Quote */}
          <motion.div
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            custom={0}
            className="rounded-2xl border border-border-subtle bg-surface/30 p-8"
          >
            <div className="mb-4 text-2xl text-emerald-accent">"</div>
            <p className="mb-6 text-base leading-relaxed text-text-muted italic">
              Excellent tool's neotical healthcare entologies with the neumord OMOP analytics
              instrument, asoscielonix and actir doepths are calm, professioing, precise and
              sophisticates.
            </p>
            <div>
              <div className="text-sm font-semibold text-text-bright">Jicamth Nuale</div>
              <div className="text-xs text-text-dim">Commerce Manager</div>
            </div>
          </motion.div>

          {/* CTA Card */}
          <motion.div
            variants={fadeUp}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            custom={1}
            id="cta"
            className="neumorphic-card flex flex-col items-center justify-center p-10 text-center"
          >
            <h3 className="mb-6 text-2xl font-bold text-text-bright">Get Started</h3>
            <a
              href="/quality"
              className="btn-emerald inline-flex items-center gap-2 text-base no-underline"
            >
              <ExternalLink className="h-5 w-5" />
              Get Started
            </a>
            <p className="mt-4 text-xs text-text-dim">Connect your OMOP CDM in minutes</p>
          </motion.div>
        </div>
      </div>
    </section>
  );
}

// ── Footer ──────────────────────────────────────────────────
function Footer() {
  return (
    <footer className="border-t border-border-subtle px-6 py-8">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 md:flex-row">
        <div className="flex items-center gap-2">
          <div className="h-4 w-4 rounded-full border-[1.5px] border-emerald-accent" />
          <span className="text-sm font-semibold text-text-muted">OPAL</span>
        </div>
        <p className="text-xs text-text-dim">
          &copy; {new Date().getFullYear()} OPAL — OMOP Platform for Analytics & Lineage
        </p>
      </div>
    </footer>
  );
}

// ── Main Landing Page ───────────────────────────────────────
export default function LandingPage() {
  return (
    <div className="relative min-h-screen bg-deep-base">
      <GlassNav />
      <HeroSection />
      <StatsSection />
      <FeaturesSection />
      <TestimonialSection />
      <Footer />
    </div>
  );
}
