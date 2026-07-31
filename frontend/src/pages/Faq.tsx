import {
  BookOpen,
  ClipboardList,
  CreditCard,
  HelpCircle,
  Layers,
  Menu,
  MessageCircle,
  Moon,
  Plug,
  Rocket,
  Server,
  Shield,
  ShieldCheck,
  Sun,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Footer } from '@/components/layout/Footer'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { useThemeStore } from '@/stores/themeStore'

const CATEGORY_ICONS: Record<string, typeof Rocket> = {
  'Getting Started': Rocket,
  'Broker Connections': Plug,
  'Strategies & Automation': Layers,
  'Order Execution': Zap,
  'Risk Management': Shield,
  'Platform & Hosting': Server,
  'Security & Privacy': ShieldCheck,
  'Plans & Billing': CreditCard,
  'Support & Documentation': MessageCircle,
}

const CATEGORY_DESCRIPTIONS: Record<string, string> = {
  'Getting Started': 'What Max Algos is and who it is built for',
  'Broker Connections': 'Connecting and managing your broker accounts',
  'Strategies & Automation': 'Building, running, and managing trading strategies',
  'Order Execution': 'How signals become real broker orders',
  'Risk Management': 'Controls that protect your capital',
  'Platform & Hosting': 'How the platform runs and stays online',
  'Security & Privacy': 'How your credentials and data are protected',
  'Plans & Billing': 'Pricing and subscription details',
  'Support & Documentation': 'Where to get help',
}

const faqData = [
  {
    category: 'Getting Started',
    questions: [
      {
        question: 'What is Max Algos?',
        answer:
          'Max Algos is a professional algorithmic trading platform that lets you automate your trading strategies without building your own infrastructure. Connect your broker, build or import a strategy, and let Max Algos monitor the market and place orders on your behalf - with real-time tracking and risk controls at every step.',
      },
      {
        question: 'Who is Max Algos built for?',
        answer:
          'Max Algos is designed for retail traders, professional and proprietary traders, options traders, TradingView users, and strategy developers - whether you are running a single strategy or managing several at once across multiple brokers.',
      },
      {
        question: 'Do I need programming knowledge?',
        answer:
          'No. You can build strategies visually with the Strategy Builder, or connect signals from TradingView and other platforms via webhooks - no code required. If you do want to code, the platform also exposes a REST API and Python strategy hosting for full custom control.',
      },
      {
        question: 'What markets and instruments can I trade?',
        answer:
          'Equity, Futures, Options, Commodities, and Currency derivatives, across NSE, BSE, NFO, BFO, MCX, CDS, and more - depending on which segments your connected broker and exchange membership support.',
      },
    ],
  },
  {
    category: 'Broker Connections',
    questions: [
      {
        question: 'Which brokers are supported?',
        answer:
          'Max Algos integrates with 25+ Indian brokers, including Zerodha, Angel One, Upstox, Dhan, Fyers, 5paisa, Alice Blue, Flattrade, Shoonya, Firstock, Motilal Oswal, Zebu, and more, with new broker integrations added on an ongoing basis.',
      },
      {
        question: 'How do I connect my broker?',
        answer:
          'Go to Broker Management and choose your broker. You authenticate directly through your broker’s own secure login or API flow - Max Algos never sees or stores your broker password.',
      },
      {
        question: 'Do I need to log in to my broker every day?',
        answer:
          'Yes. Indian brokers require daily re-authentication for regulatory reasons - broker sessions expire automatically, typically overnight. Max Algos will flag when a broker session needs to be refreshed so you can reconnect in a couple of clicks.',
      },
      {
        question: 'Can I connect multiple broker accounts?',
        answer:
          'Yes. You can connect several broker accounts at once, choose which one powers your live market data feed, and route different strategies or orders to different brokers.',
      },
    ],
  },
  {
    category: 'Strategies & Automation',
    questions: [
      {
        question: 'What is a strategy?',
        answer:
          'A strategy defines the rules Max Algos follows to enter and exit trades on your behalf - entry conditions, exit conditions, stop loss, target, position sizing, and the symbols and brokers it should trade on.',
      },
      {
        question: 'How can I create a strategy?',
        answer:
          'Build one visually with the Strategy Builder, connect a TradingView Pine Script alert via webhook, wire up a webhook from any platform that can send HTTP signals, or write your own Python strategy using the built-in strategy host.',
      },
      {
        question: 'Can I run multiple strategies at the same time?',
        answer:
          'Yes. Each strategy runs and is monitored independently, so you can operate several strategies - across different symbols and brokers - at once.',
      },
      {
        question: 'Can I pause a strategy without deleting it?',
        answer:
          'Yes. Strategies can be toggled active or inactive at any time. Your configuration, symbol mappings, and history stay intact while a strategy is paused.',
      },
      {
        question: 'Can I backtest a strategy before going live?',
        answer:
          'Yes. Strategies can be backtested against historical data before you risk real capital, and you can also run strategies in Sandbox mode with simulated ₹1 Crore capital and realistic margin/exchange-timing behavior for further validation.',
      },
    ],
  },
  {
    category: 'Order Execution',
    questions: [
      {
        question: 'How are orders executed?',
        answer:
          'When your strategy generates a signal - from a condition match, a webhook, or a TradingView alert - Max Algos validates it and sends the order to your connected broker through that broker’s API. Execution speed depends on your broker and exchange response times.',
      },
      {
        question: 'What order types are supported?',
        answer:
          'Market, Limit, Stop-Loss (SL), and Stop-Loss Market (SL-M) orders are supported, subject to what your specific broker allows for the exchange segment you’re trading.',
      },
      {
        question: 'Can I automate stop loss and target?',
        answer:
          'Yes. Strategies can manage stop loss, target, and position square-off automatically as part of their configured rules.',
      },
      {
        question: 'What happens if an order fails?',
        answer:
          'Failed orders are logged with the broker’s actual error message (e.g. session expired, margin shortfall, invalid symbol) so you can see exactly what happened and take action - reconnect your broker, add funds, or adjust the strategy.',
      },
    ],
  },
  {
    category: 'Risk Management',
    questions: [
      {
        question: 'Can I set daily loss limits?',
        answer:
          'Yes. Deployed strategies support risk controls such as daily loss limits, maximum trade counts, and cooldown periods between signals, so a strategy stops itself before losses compound.',
      },
      {
        question: 'Can I restrict trading hours?',
        answer:
          'Yes. Strategies can be configured with a start time, end time, and square-off time, so they only act within your chosen trading window and close out automatically at the end of the day.',
      },
      {
        question: 'Does every strategy have its own risk settings?',
        answer:
          'Yes. Risk parameters, capital allocation, and trading windows are configured per strategy, so one strategy’s settings never affect another.',
      },
    ],
  },
  {
    category: 'Platform & Hosting',
    questions: [
      {
        question: 'Does my computer need to stay on?',
        answer:
          'Max Algos runs on a server you control - your own machine or a VPS. Whatever it’s running on needs to stay online and connected to the internet for strategies to keep executing; it does not need to be your personal laptop.',
      },
      {
        question: 'Can I access Max Algos from multiple devices?',
        answer:
          'Yes. The dashboard is a web application, so you can securely log in and monitor your strategies, positions, and orders from any browser on desktop or mobile.',
      },
      {
        question: 'Does Max Algos provide real-time market data?',
        answer:
          'Yes. A unified WebSocket feed streams live prices, quotes, and depth from your connected broker, normalized into a consistent format for the dashboard, option chain, and your strategies.',
      },
    ],
  },
  {
    category: 'Security & Privacy',
    questions: [
      {
        question: 'Is my trading data and are my credentials secure?',
        answer:
          'Yes. Broker credentials and tokens are encrypted before storage, all communication uses HTTPS, and the platform includes CSRF protection, rate limiting, and secure session management. Because it runs on infrastructure you control, your trading data never passes through a third party.',
      },
      {
        question: 'Does Max Algos ever see my broker password?',
        answer:
          'No. Authentication happens directly through your broker’s own login or API flow. Max Algos only ever stores the resulting encrypted session token, never your password.',
      },
      {
        question: 'Who can see my strategies?',
        answer:
          'Only you. Strategies are private by default and are only visible to others if you explicitly publish them to the Marketplace.',
      },
    ],
  },
  {
    category: 'Plans & Billing',
    questions: [
      {
        question: 'How much does Max Algos cost?',
        answer:
          'Max Algos is a commercial platform with a platform subscription that unlocks the trading tools and automation, plus optional per-strategy fees for premium strategies you subscribe to on the Marketplace. Reach out to us for current plan details and pricing.',
      },
      {
        question: 'What are Marketplace strategy fees?',
        answer:
          'Some strategies published to the Marketplace by their creators carry their own subscription price, separate from your platform plan. Subscribing clones that strategy into your own account so you can deploy it on your broker.',
      },
      {
        question: 'What happens if my subscription lapses?',
        answer:
          'Your strategies and configuration remain saved, but automated execution and premium features are paused until your subscription is renewed.',
      },
    ],
  },
  {
    category: 'Support & Documentation',
    questions: [
      {
        question: 'How can I get support?',
        answer:
          'Through the in-app Help Center, our documentation site, community channels, and email support - with priority support available on eligible plans.',
      },
      {
        question: 'Where can I learn to use Max Algos?',
        answer:
          'Our documentation covers Getting Started, broker setup, strategy creation, TradingView integration, risk management, and the full API reference.',
      },
    ],
  },
]

export default function Faq() {
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
      {/* Navbar */}
      <header className="sticky top-0 z-30 h-16 w-full border-b bg-background/90 backdrop-blur">
        <nav className="container mx-auto px-4 flex h-full items-center justify-between">
          {/* Logo */}
          <div className="flex items-center gap-2">
            {/* Mobile menu button */}
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
                  <Link
                    to="/"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      className="h-5 w-5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"
                      />
                    </svg>
                    Home
                  </Link>
                  <Link
                    to="/faq"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    <HelpCircle className="h-5 w-5" />
                    FAQ
                  </Link>
                  <a
                    href="https://maxalgos.in/discord"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                  >
                    <MessageCircle className="h-5 w-5" />
                    Community
                  </a>
                  <a
                    href="https://maxalgos.in/roadmap"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                  >
                    <ClipboardList className="h-5 w-5" />
                    Roadmap
                  </a>
                  <a
                    href="https://docs.maxalgos.in"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                  >
                    <BookOpen className="h-5 w-5" />
                    Docs
                  </a>
                </div>
              </SheetContent>
            </Sheet>

            <Link to="/" className="flex items-center gap-2">
              <img src="/logo.png" alt="Max Algos" className="h-8 w-8" />
              <span className="text-xl font-bold hidden sm:inline">Max Algos</span>
            </Link>
          </div>

          {/* Desktop Navigation */}
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

          {/* Right side */}
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleMode}
              aria-label={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {mode === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </Button>
          </div>
        </nav>
      </header>

      {/* Main Content */}
      <main className="flex-1">
        <div className="container mx-auto px-4 py-12">
          {/* Header */}
          <div className="text-center mb-12">
            <h1 className="text-4xl lg:text-5xl font-bold mb-4">Frequently Asked Questions</h1>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              Everything you need to know before you trust Max Algos with your trading -
              brokers, automation, execution, risk controls, and security.
            </p>
          </div>

          {/* FAQ Categories */}
          <div className="max-w-4xl mx-auto space-y-8">
            {faqData.map((category) => {
              const CategoryIcon = CATEGORY_ICONS[category.category] ?? HelpCircle
              return (
                <Card key={category.category}>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <CategoryIcon className="h-5 w-5 text-primary" />
                      {category.category}
                    </CardTitle>
                    <CardDescription>{CATEGORY_DESCRIPTIONS[category.category]}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <Accordion type="single" collapsible className="w-full">
                      {category.questions.map((faq, index) => (
                        <AccordionItem key={index} value={`${category.category}-${index}`}>
                          <AccordionTrigger className="text-left">{faq.question}</AccordionTrigger>
                          <AccordionContent className="text-muted-foreground">
                            {faq.answer}
                          </AccordionContent>
                        </AccordionItem>
                      ))}
                    </Accordion>
                  </CardContent>
                </Card>
              )
            })}
          </div>

          {/* Resources Section */}
          <div className="max-w-4xl mx-auto mt-16">
            <h2 className="text-2xl font-bold text-center mb-8">Need More Help?</h2>
            <div className="grid md:grid-cols-3 gap-6">
              <Card className="text-center">
                <CardHeader>
                  <BookOpen className="h-10 w-10 mx-auto text-primary" />
                  <CardTitle className="text-lg">Documentation</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground mb-4">
                    Comprehensive guides and API references
                  </p>
                  <Button variant="outline" asChild>
                    <a href="https://docs.maxalgos.in" target="_blank" rel="noopener noreferrer">
                      Read Docs
                    </a>
                  </Button>
                </CardContent>
              </Card>

              <Card className="text-center">
                <CardHeader>
                  <MessageCircle className="h-10 w-10 mx-auto text-primary" />
                  <CardTitle className="text-lg">Discord Community</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground mb-4">
                    Join our active community for support
                  </p>
                  <Button variant="outline" asChild>
                    <a href="https://maxalgos.in/discord" target="_blank" rel="noopener noreferrer">
                      Join Discord
                    </a>
                  </Button>
                </CardContent>
              </Card>

              <Card className="text-center">
                <CardHeader>
                  <ClipboardList className="h-10 w-10 mx-auto text-primary" />
                  <CardTitle className="text-lg">Talk to Us</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground mb-4">
                    Questions about plans, pricing, or your setup? Reach our team directly
                  </p>
                  <Button variant="outline" asChild>
                    <a href="https://docs.maxalgos.in" target="_blank" rel="noopener noreferrer">
                      Contact Support
                    </a>
                  </Button>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <Footer />
    </div>
  )
}
