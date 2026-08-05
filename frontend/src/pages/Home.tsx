import {
  Activity,
  ArrowRight,
  BarChart2,
  Bot,
  BrainCircuit,
  ChevronRight,
  Code2,
  LineChart,
  Lock,
  LogIn,
  Menu,
  Moon,
  Rocket,
  Settings,
  Shield,
  ShieldCheck,
  Sparkles,
  Sun,
  TrendingUp,
  Wifi,
  Zap,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Marquee } from '@/components/ui/marquee'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { useThemeStore } from '@/stores/themeStore'

// ─── Data ──────────────────────────────────────────────────────────────────────

const brokers = [
  'Alice Blue',
  'Zerodha',
  'Upstox',
  'Angel One',
  'Fyers',
  'Dhan',
  'Shoonya',
  'IFL Securities',
  'Firstock',
  'FlatTrade',
  'Wisdom Capital',
  'Zebu',
  'Motilal Oswal',
  '5paisa',
  'IndMoney',
  'Compositedge',
  'IIFL',
  'IBULLS',
  'Arrow',
  'Definedge',
  'Delta Exchange',
  'Pocketful',
  'RMoney',
  'JainamXTS',
  'BNR Securities',
]

const integrations = [
  'Amibroker',
  'TradingView',
  'GoCharting',
  'Python',
  'MetaTrader',
  'N8N',
  'Java',
  'Go',
  '.NET',
  'Node.js',
  'Rust',
  'ChartInk',
  'Excel',
  'Google Sheets',
  'OpenClaw',
]

const features = [
  {
    icon: BrainCircuit,
    color: 'text-cat-2',
    bg: 'bg-cat-2/10',
    title: 'Strategy Builder',
    desc: 'Build advanced strategies with our no-code/low-code strategy builder — no programming required.',
  },
  {
    icon: BarChart2,
    color: 'text-info',
    bg: 'bg-info/10',
    title: 'Backtesting Engine',
    desc: 'Tick-by-tick backtesting with realistic market simulations and slippage modelling.',
  },
  {
    icon: Activity,
    color: 'text-profit',
    bg: 'bg-success/10',
    title: 'Live Trading',
    desc: 'Deploy strategies in real-time with advanced risk management and position sizing.',
  },
  {
    icon: LineChart,
    color: 'text-brand',
    bg: 'bg-brand/10',
    title: 'Options Analytics',
    desc: 'Advanced options analytics and Greeks calculation with 12-tool options analytics suite.',
  },
  {
    icon: TrendingUp,
    color: 'text-cat-4',
    bg: 'bg-cat-4/10',
    title: 'Portfolio Analytics',
    desc: 'Comprehensive portfolio analysis and performance tracking with detailed P&L reports.',
  },
  {
    icon: Code2,
    color: 'text-cat-3',
    bg: 'bg-cat-3/10',
    title: 'API Access',
    desc: 'Full REST API and WebSocket for custom integrations and third-party automation.',
  },
]

const capabilities = [
  {
    icon: Wifi,
    title: 'Real-time Market Data',
    desc: 'Sub-second latency across all exchanges with tick-by-tick precision.',
  },
  {
    icon: Shield,
    title: 'Advanced Risk Management',
    desc: 'Multi-level risk controls and position-sizing safeguards.',
  },
  {
    icon: Bot,
    title: 'Paper Trading',
    desc: 'Practice strategies with virtual money — zero risk, real experience.',
  },
  {
    icon: Sparkles,
    title: 'Custom Indicators',
    desc: 'Build and display custom technical indicators using Python.',
  },
  {
    icon: Zap,
    title: 'Automated Execution',
    desc: 'Smart order routing and execution algorithms for optimal fills.',
  },
]

const stats = [
  { value: '10K+', label: 'Active Traders' },
  { value: '30+', label: 'Supported Brokers' },
  { value: '1M+', label: 'Strategies Deployed' },
  { value: '99.9%', label: 'Uptime' },
  { value: '<50ms', label: 'Average Latency' },
  { value: '24/7', label: 'Support' },
]

const trustBadges = [
  { icon: ShieldCheck, label: 'SOC 2 Type II Certified' },
  { icon: Lock, label: '256-bit SSL Encryption' },
  { icon: Activity, label: '99.9% Uptime SLA' },
  { icon: Shield, label: 'SEBI Compliant' },
  { icon: Settings, label: 'ISO 27001 Certified' },
]

// ─── Animated counter hook ───────────────────────────────────────────────────

function useCountUp(target: string, duration = 1500) {
  const [display, setDisplay] = useState('0')
  const ref = useRef<HTMLDivElement>(null)
  const started = useRef(false)

  useEffect(() => {
    const numericPart = parseFloat(target.replace(/[^0-9.]/g, ''))
    const suffix = target.replace(/[0-9.]/g, '')
    if (Number.isNaN(numericPart)) {
      setDisplay(target)
      return
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !started.current) {
          started.current = true
          const start = performance.now()
          const step = (now: number) => {
            const progress = Math.min((now - start) / duration, 1)
            const eased = 1 - (1 - progress) ** 3
            const current = Math.round(eased * numericPart * 10) / 10
            setDisplay(`${current % 1 === 0 ? current : current.toFixed(1)}${suffix}`)
            if (progress < 1) requestAnimationFrame(step)
          }
          requestAnimationFrame(step)
        }
      },
      { threshold: 0.5 }
    )

    if (ref.current) observer.observe(ref.current)
    return () => observer.disconnect()
  }, [target, duration])

  return { display, ref }
}

// ─── StatCard ────────────────────────────────────────────────────────────────

function StatCard({ value, label }: { value: string; label: string }) {
  const { display, ref } = useCountUp(value)
  return (
    <div ref={ref} className="text-center">
      <div className="text-3xl sm:text-4xl font-bold text-brand tabular-nums">{display}</div>
      <div className="text-sm text-muted-foreground mt-1">{label}</div>
    </div>
  )
}

// ─── Mini animated chart ──────────────────────────────────────────────────────

function MiniChart() {
  const points = [
    { x: 0, y: 80 },
    { x: 50, y: 65 },
    { x: 100, y: 72 },
    { x: 150, y: 45 },
    { x: 200, y: 55 },
    { x: 250, y: 38 },
    { x: 300, y: 30 },
    { x: 350, y: 20 },
    { x: 400, y: 35 },
    { x: 450, y: 15 },
    { x: 500, y: 25 },
  ]
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')
  const area = `${path} L 500 120 L 0 120 Z`

  return (
    <div className="relative w-full h-40 rounded-xl overflow-hidden border border-border bg-card/50">
      <svg className="w-full h-full" viewBox="0 0 500 120" preserveAspectRatio="none">
        <defs>
          <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--brand)" stopOpacity="0.3" />
            <stop offset="100%" stopColor="var(--brand)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#chartFill)" />
        <path
          d={path}
          fill="none"
          stroke="var(--brand)"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {/* Animated dot at the end */}
        <circle cx="500" cy="25" r="4" fill="var(--brand)">
          <animate attributeName="opacity" values="1;0.3;1" dur="1.5s" repeatCount="indefinite" />
        </circle>
      </svg>
      {/* Labels */}
      <div className="absolute top-2 left-3 flex items-center gap-2">
        <span className="text-xs font-bold text-foreground">NIFTY 50</span>
        <span className="text-xs text-profit font-semibold">▲ +1.93%</span>
      </div>
      <div className="absolute top-2 right-3 flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
        <span className="text-xs text-profit font-semibold">Live</span>
      </div>
    </div>
  )
}

// ─── Home Page ────────────────────────────────────────────────────────────────

export default function Home() {
  const { mode, toggleMode } = useThemeStore()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const navLinks = [
    { href: '/', label: 'Home', internal: true },
    { href: '/faq', label: 'FAQ', internal: true },
    { href: 'https://maxalgos.in/discord', label: 'Community', internal: false },
    { href: 'https://maxalgos.in/roadmap', label: 'Roadmap', internal: false },
    { href: 'https://docs.maxalgos.in', label: 'Docs', internal: false },
  ]

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* @keyframes marquee lives in index.css, shared with components/ui/marquee.tsx */}
      <style>{`
        @keyframes fadeInUp { from { opacity: 0; transform: translateY(24px) } to { opacity: 1; transform: translateY(0) } }
        .animate-fade-in-up { animation: fadeInUp 0.7s ease both; }
        .delay-100 { animation-delay: 0.1s; }
        .delay-200 { animation-delay: 0.2s; }
        .delay-300 { animation-delay: 0.3s; }
        .delay-400 { animation-delay: 0.4s; }
        .delay-500 { animation-delay: 0.5s; }
      `}</style>

      {/* ── Navbar ─────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 h-16 w-full border-b bg-background/90 backdrop-blur">
        <nav className="container mx-auto px-4 flex h-full items-center justify-between">
          {/* Logo */}
          <div className="flex items-center gap-2">
            <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
              <SheetTrigger asChild className="lg:hidden">
                <Button variant="ghost" size="icon" aria-label="Open menu">
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-80">
                <SheetHeader className="sr-only">
                  <SheetTitle>Navigation Menu</SheetTitle>
                  <SheetDescription>Main navigation and quick access links</SheetDescription>
                </SheetHeader>
                <div className="flex items-center gap-2 mb-8">
                  <img src="/logo.png" alt="Max Algos" className="h-8 w-8" />
                  <span className="text-xl font-semibold">Max Algos</span>
                </div>
                <div className="flex flex-col gap-2">
                  {navLinks.map((link) =>
                    link.internal ? (
                      <Link
                        key={link.href}
                        to={link.href}
                        className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent text-sm font-medium"
                        onClick={() => setMobileMenuOpen(false)}
                      >
                        {link.label}
                      </Link>
                    ) : (
                      <a
                        key={link.href}
                        href={link.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent text-sm font-medium"
                        onClick={() => setMobileMenuOpen(false)}
                      >
                        {link.label}
                      </a>
                    )
                  )}
                  <Link
                    to="/login"
                    className="flex items-center gap-2 px-4 py-2 rounded-md bg-brand text-brand-foreground hover:bg-brand/90 mt-2 text-sm font-semibold"
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    <LogIn className="h-4 w-4" /> Log In
                  </Link>
                </div>
              </SheetContent>
            </Sheet>

            <Link to="/" className="flex items-center gap-2">
              <img src="/logo.png" alt="Max Algos" className="h-8 w-8" />
              <span className="text-xl font-bold hidden sm:inline">Max Algos</span>
            </Link>
          </div>

          {/* Desktop nav links */}
          <div className="hidden lg:flex items-center gap-1">
            {navLinks.map((link) =>
              link.internal ? (
                <Link key={link.href} to={link.href}>
                  <Button variant="ghost" size="sm">
                    {link.label}
                  </Button>
                </Link>
              ) : (
                <a key={link.href} href={link.href} target="_blank" rel="noopener noreferrer">
                  <Button variant="ghost" size="sm">
                    {link.label}
                  </Button>
                </a>
              )
            )}
          </div>

          {/* Right actions */}
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleMode}
              aria-label={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {mode === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </Button>
            <Link to="/login" className="hidden sm:block">
              <Button variant="ghost" size="sm">
                Log In
              </Button>
            </Link>
            <Link to="/login">
              <Button
                size="sm"
                className="bg-brand hover:bg-brand/90 text-brand-foreground border-none font-semibold"
              >
                Get Started
              </Button>
            </Link>
          </div>
        </nav>
      </header>

      <main className="flex-1">
        {/* ── Hero ───────────────────────────────────────────────────────────── */}
        <section className="relative overflow-hidden">
          {/* Background glow */}
          <div className="absolute inset-0 -z-10 overflow-hidden">
            <div className="absolute top-[-10%] left-1/2 -translate-x-1/2 w-[800px] h-[500px] rounded-full bg-brand/10 dark:bg-brand/5 blur-[100px]" />
          </div>

          <div className="container mx-auto px-4 pt-20 pb-12 sm:pt-28 sm:pb-20">
            <div className="grid lg:grid-cols-2 gap-12 items-center max-w-7xl mx-auto">
              {/* Left: copy */}
              <div>
                {/* NEW badge */}
                <Link
                  to="/tools"
                  className="animate-fade-in-up inline-flex items-center gap-2 rounded-full border border-brand/30 bg-brand/10 px-4 py-1.5 text-xs font-semibold uppercase tracking-[0.2em] mb-6 transition-colors hover:border-brand/50"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-brand shadow-[0_0_8px] shadow-brand/60" />
                  <span className="text-brand">New in V2</span>
                  <span className="text-muted-foreground">— 12-Tool Options Suite</span>
                  <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                </Link>

                <h1 className="animate-fade-in-up delay-100 text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight mb-4 leading-tight">
                  Your Professional
                  <span className="block text-brand">Algo Trading</span>
                  Platform
                </h1>

                <p className="animate-fade-in-up delay-200 text-base sm:text-lg text-muted-foreground max-w-lg mb-8">
                  Build, test and deploy algorithmic trading strategies across 30+ brokers. Advanced
                  analytics, real-time data, and powerful automation — all in one platform.
                </p>

                {/* CTA buttons */}
                <div className="animate-fade-in-up delay-300 flex flex-col sm:flex-row gap-3 mb-8">
                  <Button
                    size="lg"
                    className="bg-brand hover:bg-brand/90 text-brand-foreground font-semibold text-base h-12 px-7 shadow-lg shadow-brand/20"
                    asChild
                  >
                    <Link to="/login">
                      <Rocket className="mr-2 h-5 w-5" />
                      Start Trading Now
                    </Link>
                  </Button>
                </div>

                {/* Trust micro-copy */}
                <div className="animate-fade-in-up delay-400 flex flex-wrap gap-4 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1.5">
                    <ShieldCheck className="h-3.5 w-3.5 text-profit" />
                    No Credit Card Required
                  </span>
                  <span className="flex items-center gap-1.5">
                    <Sparkles className="h-3.5 w-3.5 text-brand" />
                    Free Forever Plan
                  </span>
                  <span className="flex items-center gap-1.5">
                    <Lock className="h-3.5 w-3.5 text-info" />
                    Bank Grade Security
                  </span>
                </div>
              </div>

              {/* Right: mock dashboard */}
              <div className="animate-fade-in-up delay-300 hidden lg:block">
                <div className="rounded-2xl border border-border bg-card shadow-2xl overflow-hidden">
                  {/* Dashboard header bar */}
                  <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/40">
                    <div className="flex items-center gap-2">
                      <img src="/logo.png" alt="Max Algos" className="h-5 w-5" />
                      <span className="text-sm font-semibold">Max Algos</span>
                    </div>
                    <div className="flex gap-1.5">
                      <div className="w-2.5 h-2.5 rounded-full bg-destructive" />
                      <div className="w-2.5 h-2.5 rounded-full bg-brand" />
                      <div className="w-2.5 h-2.5 rounded-full bg-success" />
                    </div>
                  </div>

                  <div className="p-4 space-y-4">
                    {/* Chart */}
                    <MiniChart />

                    {/* Stats row */}
                    <div className="grid grid-cols-3 gap-3">
                      {[
                        { label: 'Total P&L', value: '+₹1,34,670', color: 'text-profit' },
                        { label: 'Win Rate', value: '67.8%', color: 'text-brand' },
                        { label: 'Profit Factor', value: '2.34', color: 'text-info' },
                      ].map((s) => (
                        <div key={s.label} className="rounded-lg bg-muted/50 p-3 text-center">
                          <div className={`text-sm font-bold ${s.color}`}>{s.value}</div>
                          <div className="text-[10px] text-muted-foreground mt-0.5">{s.label}</div>
                        </div>
                      ))}
                    </div>

                    {/* Active strategies */}
                    <div className="space-y-2">
                      {[
                        {
                          name: 'Momentum Pro',
                          sym: 'NIFTY 50',
                          pnl: '+₹856.87',
                          color: 'text-profit',
                        },
                        {
                          name: 'Breakout Scanner',
                          sym: 'BANKNIFTY',
                          pnl: '+₹223.65',
                          color: 'text-profit',
                        },
                        {
                          name: 'Mean Reversion',
                          sym: 'BANKNIFTY',
                          pnl: '-₹123.12',
                          color: 'text-loss',
                        },
                      ].map((row) => (
                        <div
                          key={row.name}
                          className="flex items-center justify-between rounded-lg bg-muted/30 px-3 py-2 text-xs"
                        >
                          <div>
                            <div className="font-semibold text-foreground">{row.name}</div>
                            <div className="text-muted-foreground">{row.sym}</div>
                          </div>
                          <span className={`font-bold ${row.color}`}>{row.pnl}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── Trust badges ────────────────────────────────────────────────────── */}
        <section className="border-y border-border bg-muted/30 py-6">
          <div className="container mx-auto px-4">
            <p className="text-center text-xs font-semibold uppercase tracking-[0.25em] text-muted-foreground mb-5">
              Trusted by 10,000+ algorithmic traders
            </p>
            <div className="flex flex-wrap justify-center gap-6 sm:gap-10">
              {trustBadges.map(({ icon: Icon, label }) => (
                <div key={label} className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Icon className="h-4 w-4 text-brand shrink-0" />
                  <span>{label}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Broker integration marquee ──────────────────────────────────────── */}
        <section className="py-14">
          <div className="container mx-auto px-4 mb-6 text-center">
            <p className="text-xs font-semibold uppercase tracking-[0.25em] text-brand mb-2">
              Seamless Integration with 30+ Platforms
            </p>
          </div>
          <Marquee
            items={brokers.map((name) => ({
              key: name,
              content: (
                <span className="rounded-full border border-border bg-card/60 px-4 py-2 text-sm text-foreground/80 whitespace-nowrap shadow-sm">
                  {name}
                </span>
              ),
            }))}
            speed={40}
          />
          <div className="mt-3">
            <Marquee
              items={integrations.map((name) => ({
                key: name,
                content: (
                  <span className="rounded-full border border-border bg-card/60 px-4 py-2 text-sm text-foreground/80 whitespace-nowrap shadow-sm">
                    {name}
                  </span>
                ),
              }))}
              speed={30}
            />
          </div>
        </section>

        {/* ── Features grid ───────────────────────────────────────────────────── */}
        <section className="py-16 sm:py-20 bg-muted/20">
          <div className="container mx-auto px-4">
            <div className="text-center max-w-2xl mx-auto mb-12">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-brand/30 bg-brand/10 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-brand mb-4">
                <Sparkles className="h-3.5 w-3.5" />
                Powerful Features
              </span>
              <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight mb-4">
                Everything You Need to
                <br className="hidden sm:block" /> Trade Like a Pro
              </h2>
              <p className="text-muted-foreground text-base sm:text-lg">
                Professional tools designed for serious algorithmic traders.
              </p>
            </div>

            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5 max-w-6xl mx-auto">
              {features.map(({ icon: Icon, color, bg, title, desc }) => (
                <Card
                  key={title}
                  className="group transition-all hover:shadow-md hover:-translate-y-0.5 cursor-default"
                >
                  <CardContent className="space-y-3 pt-6">
                    <div
                      className={`flex h-11 w-11 items-center justify-center rounded-xl ${bg} ${color}`}
                    >
                      <Icon className="h-5 w-5" />
                    </div>
                    <h3 className="font-bold text-lg">{title}</h3>
                    <p className="text-sm text-muted-foreground leading-relaxed">{desc}</p>
                    <div className="flex items-center gap-1 text-xs text-brand font-semibold group-hover:gap-2 transition-all">
                      Learn more <ChevronRight className="h-3.5 w-3.5" />
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* ── Advanced Capabilities ───────────────────────────────────────────── */}
        <section className="py-16 sm:py-20">
          <div className="container mx-auto px-4">
            <div className="text-center max-w-2xl mx-auto mb-12">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-info/30 bg-info/10 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-info mb-4">
                <Zap className="h-3.5 w-3.5" />
                Built for Professionals
              </span>
              <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight mb-4">
                Advanced Capabilities
              </h2>
              <p className="text-muted-foreground">
                Institutional-grade infrastructure with retail-friendly pricing.
              </p>
            </div>

            <div className="grid lg:grid-cols-2 gap-10 max-w-6xl mx-auto items-center">
              {/* Capability list */}
              <div className="space-y-3">
                {capabilities.map(({ icon: Icon, title, desc }, i) => (
                  <div
                    key={title}
                    className="flex gap-4 rounded-xl border border-border bg-card p-4 transition-all hover:border-brand/30 hover:bg-brand/5 cursor-default group"
                    style={{ animationDelay: `${i * 80}ms` }}
                  >
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand/10 text-brand">
                      <Icon className="h-5 w-5" />
                    </div>
                    <div>
                      <h3 className="font-semibold text-sm mb-1">{title}</h3>
                      <p className="text-xs text-muted-foreground leading-relaxed">{desc}</p>
                    </div>
                  </div>
                ))}
              </div>

              {/* Live chart panel */}
              <div className="rounded-2xl border border-border bg-card shadow-xl p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-xs text-muted-foreground font-medium">
                      NSE · BSE · MCX · NCDEX · CDS
                    </div>
                    <div className="text-lg font-bold mt-0.5">Real-time Market Data</div>
                    <div className="text-sm text-muted-foreground">
                      Multi-exchange with sub-second latency
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-profit font-semibold">
                    <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
                    Live
                  </div>
                </div>
                <MiniChart />
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { label: 'Latency', value: '<50ms', color: 'text-profit' },
                    { label: 'Exchanges', value: '5+', color: 'text-info' },
                    { label: 'Instruments', value: '50K+', color: 'text-brand' },
                    { label: 'Uptime', value: '99.9%', color: 'text-cat-2' },
                  ].map((s) => (
                    <div key={s.label} className="rounded-lg bg-muted/50 p-3">
                      <div className={`text-base font-bold ${s.color}`}>{s.value}</div>
                      <div className="text-[10px] text-muted-foreground">{s.label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── Stats counters ──────────────────────────────────────────────────── */}
        <section className="py-14 border-y border-border bg-muted/20">
          <div className="container mx-auto px-4">
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-8 max-w-5xl mx-auto">
              {stats.map((s) => (
                <StatCard key={s.label} value={s.value} label={s.label} />
              ))}
            </div>
          </div>
        </section>

        {/* ── CTA Banner ─────────────────────────────────────────────────────── */}
        <section className="py-20">
          <div className="container mx-auto px-4">
            <div className="relative rounded-3xl overflow-hidden bg-gradient-to-br from-brand to-brand/85 text-brand-foreground p-10 sm:p-14 text-center shadow-2xl shadow-brand/20 max-w-5xl mx-auto">
              {/* Background decoration */}
              <div className="absolute inset-0 -z-0 overflow-hidden">
                <div className="absolute -top-1/2 -right-1/4 w-[600px] h-[600px] rounded-full bg-white/10 blur-3xl" />
                <div className="absolute -bottom-1/2 -left-1/4 w-[400px] h-[400px] rounded-full bg-white/10 blur-3xl" />
              </div>

              <div className="relative z-10">
                <div className="flex justify-center mb-5">
                  <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-white/20 backdrop-blur">
                    <TrendingUp className="h-7 w-7" />
                  </div>
                </div>
                <h2 className="text-3xl sm:text-4xl font-bold mb-4">
                  Ready to Take Your Trading to the Next Level?
                </h2>
                <p className="text-brand-foreground/85 text-base sm:text-lg max-w-xl mx-auto mb-8">
                  Join thousands of professional traders who trust Max Algos for their algorithmic
                  trading needs.
                </p>
                <div className="flex flex-col sm:flex-row gap-4 justify-center">
                  <Button
                    size="lg"
                    className="bg-background text-brand hover:bg-background/90 font-bold h-12 px-8 shadow-lg"
                    asChild
                  >
                    <Link to="/login">
                      <Rocket className="mr-2 h-5 w-5" />
                      Start Your Journey
                    </Link>
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── Landing page footer (public — different from app footer) ─────── */}
        <footer className="border-t border-border bg-card py-12">
          <div className="container mx-auto px-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-8 mb-10">
              {/* Brand */}
              <div className="col-span-2 sm:col-span-1">
                <Link to="/" className="flex items-center gap-2 mb-3">
                  <img src="/logo.png" alt="Max Algos" className="h-8 w-8" />
                  <span className="font-bold text-lg">Max Algos</span>
                </Link>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  Your professional algorithmic trading platform. Build, test, and deploy strategies
                  across 30+ brokers with institutional-grade infrastructure.
                </p>
              </div>

              {/* Product */}
              <div>
                <div className="text-xs font-bold uppercase tracking-wider text-foreground mb-3">
                  Product
                </div>
                <div className="space-y-2">
                  {[
                    'Strategy Builder',
                    'Backtesting',
                    'Live Trading',
                    'Analytics',
                    'API Documentation',
                  ].map((l) => (
                    <div key={l}>
                      <Link
                        to="/login"
                        className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                      >
                        {l}
                      </Link>
                    </div>
                  ))}
                </div>
              </div>

              {/* Resources */}
              <div>
                <div className="text-xs font-bold uppercase tracking-wider text-foreground mb-3">
                  Resources
                </div>
                <div className="space-y-2">
                  {[
                    { label: 'Documentation', href: 'https://docs.maxalgos.in' },
                    { label: 'Community', href: 'https://maxalgos.in/discord' },
                    { label: 'Roadmap', href: 'https://maxalgos.in/roadmap' },
                    { label: 'FAQ', href: '/faq' },
                  ].map((l) => (
                    <div key={l.label}>
                      {l.href.startsWith('http') ? (
                        <a
                          href={l.href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                        >
                          {l.label}
                        </a>
                      ) : (
                        <Link
                          to={l.href}
                          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                        >
                          {l.label}
                        </Link>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Company */}
              <div>
                <div className="text-xs font-bold uppercase tracking-wider text-foreground mb-3">
                  Company
                </div>
                <div className="space-y-2">
                  {['About Us', 'Careers', 'Contact Us', 'Privacy Policy', 'Terms of Service'].map(
                    (l) => (
                      <div key={l}>
                        <Link
                          to="/login"
                          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                        >
                          {l}
                        </Link>
                      </div>
                    )
                  )}
                </div>
              </div>
            </div>

            {/* Bottom bar */}
            <div className="border-t border-border pt-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-muted-foreground">
              <div>© {new Date().getFullYear()} Max Algos. All rights reserved.</div>
              <div className="flex items-center gap-4">
                <span>SEBI Compliance</span>
                <span className="text-border">|</span>
                <span>Risk Disclosure</span>
                <span className="text-border">|</span>
                <span>Security</span>
                <span className="text-border">|</span>
                <span>Sitemap</span>
              </div>
            </div>
          </div>
        </footer>
      </main>
    </div>
  )
}
