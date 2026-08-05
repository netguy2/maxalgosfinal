import { Layers, Search, Sparkles, Zap } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchCSRFToken } from '@/api/client'
import { CatalogCard } from '@/components/marketplace/CatalogCard'
import { StatCard } from '@/components/patterns/StatCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  CATALOG,
  type CatalogItem,
  type CatalogTier,
  categoriesForTier,
  itemsByTier,
} from '@/lib/marketplace-catalog'
import { openCheckout } from '@/lib/razorpay'
import { showToast } from '@/utils/toast'

interface BackendListing {
  id: number
  strategy_id: number
  name: string
  price: number
  rating: number
  reviews_count: number
  win_rate: number
  drawdown: number
  returns: number
  featured: boolean
  creator: string
  description: string
  is_subscribed: boolean
}

// 'templates' is a UI-only tab that merges the 'free' and 'pro' catalog
// tiers into one strip entry (Marketplace no longer shows them as two
// separate tabs) -- the underlying CatalogItem.tier values are untouched,
// since other code (wizard template mapping, pricing badges) still
// distinguishes free vs. pro per item.
type Tab = 'templates' | CatalogTier | 'subscriptions'

// 'ai' has no separate tab of its own: MarketplaceListing has no tier
// column to distinguish an "AI" listing from a "Premium" one server-side,
// and every seeded listing (blueprints/strategy.py's
// _init_mock_marketplace_listings) is equally real and subscribable --
// splitting them across two tabs with no reliable signal would be
// arbitrary. All backend-published listings, AI-flavored or not, render
// under the Premium tab.
const TAB_META: { tab: Tab; label: string; tagline: string }[] = [
  {
    tab: 'templates',
    label: 'Free Templates',
    tagline: 'Editable starting points — clone, customize, deploy.',
  },
  {
    tab: 'premium',
    label: 'Premium Strategies',
    tagline: 'Real, subscribable strategies -- compiled and deployed on subscribe.',
  },
  {
    tab: 'subscriptions',
    label: 'My Strategies',
    tagline: '',
  },
]

export default function Marketplace() {
  const navigate = useNavigate()
  const [listings, setListings] = useState<BackendListing[]>([])
  const [subscribed, setSubscribed] = useState<Set<number>>(new Set())
  const [activeTab, setActiveTab] = useState<Tab>('templates')
  const [category, setCategory] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  // Free/Pro templates: hide the ones without a real destination by default,
  // since cloning them wouldn't produce a working strategy.
  const [wiredOnly, setWiredOnly] = useState(true)

  const fetchMarketplace = async () => {
    try {
      const res = await fetch('/strategy/api/marketplace')
      if (res.ok) {
        const data = await res.json()
        if (data.status === 'success') {
          setListings(data.listings || [])
          setSubscribed(
            new Set(
              (data.listings || [])
                .filter((l: BackendListing) => l.is_subscribed)
                .map((l: BackendListing) => l.strategy_id)
            )
          )
        }
      }
    } catch {
      // Backend marketplace unavailable — the curated catalog still renders.
    }
  }

  useEffect(() => {
    fetchMarketplace()
    // biome-ignore lint/correctness/useExhaustiveDependencies: intentional mount-only fetch
  }, [])

  // Real backend listings become subscribable Premium catalog items.
  const backendPremium: CatalogItem[] = useMemo(
    () =>
      listings.map((l) => ({
        id: `backend-${l.strategy_id}`,
        name: l.name,
        tier: 'premium' as const,
        category: 'Published',
        asset: 'Any' as const,
        difficulty: 'Advanced' as const,
        description: l.description,
        strategyId: l.strategy_id,
        rating: l.rating,
        subscribers: l.reviews_count,
        winRate: l.win_rate,
        maxDrawdown: l.drawdown,
        monthlyReturn: l.returns,
        price: l.price,
        featured: l.featured,
      })),
    [listings]
  )

  const tierItems = useMemo((): CatalogItem[] => {
    if (activeTab === 'subscriptions') {
      return backendPremium.filter((i) => i.strategyId != null && subscribed.has(i.strategyId))
    }
    if (activeTab === 'templates') {
      return [...itemsByTier('free'), ...itemsByTier('pro')]
    }
    const base = itemsByTier(activeTab)
    if (activeTab !== 'premium') return base
    // Merge live backend listings with static catalog entries.
    // Backend entries take priority — they carry a real strategyId for
    // subscribing. Suppress any static entry whose name exactly matches a
    // backend listing so there are no duplicate cards once the DB is seeded.
    const backendNames = new Set(backendPremium.map((i) => i.name.toLowerCase()))
    const staticOnly = base.filter((i) => !backendNames.has(i.name.toLowerCase()))
    return [...backendPremium, ...staticOnly]
  }, [activeTab, backendPremium, subscribed])


  const categories = useMemo(() => {
    if (activeTab === 'subscriptions') return []
    if (activeTab === 'templates') {
      return [...new Set([...categoriesForTier('free'), ...categoriesForTier('pro')])]
    }
    return categoriesForTier(activeTab)
  }, [activeTab])

  const isTemplateTab = activeTab === 'templates'

  const filtered = useMemo(() => {
    const q = searchQuery.toLowerCase()
    return tierItems.filter((item) => {
      if (category !== 'all' && item.category !== category) return false
      if (q && !item.name.toLowerCase().includes(q) && !item.description.toLowerCase().includes(q))
        return false
      if (isTemplateTab && wiredOnly && item.signalId == null && item.optionsTemplateId == null)
        return false
      return true
    })
  }, [tierItems, category, searchQuery, isTemplateTab, wiredOnly])

  // Catalog-wide wiring stats for the templates tabs
  const templateStats = useMemo(() => {
    const templates = CATALOG.filter((i) => i.tier === 'free' || i.tier === 'pro')
    const wired = templates.filter((i) => i.signalId != null || i.optionsTemplateId != null)
    return { total: templates.length, wired: wired.length }
  }, [])

  const subscribeWithPayment = async (item: CatalogItem) => {
    const csrfToken = await fetchCSRFToken()

    const orderRes = await fetch(`/payments/marketplace/${item.strategyId}/create-order`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify({}),
    })
    const orderData = await orderRes.json()
    if (!orderRes.ok) {
      showToast.error(orderData.message || 'Could not start payment', 'strategy')
      return
    }

    let checkoutResult
    try {
      checkoutResult = await openCheckout({
        keyId: orderData.key_id,
        orderId: orderData.order_id,
        amountPaise: orderData.amount,
        currency: orderData.currency,
        name: 'Max Algos',
        description: `Subscribe to ${item.name}`,
      })
    } catch {
      showToast.info('Payment cancelled', 'strategy')
      return
    }

    const verifyRes = await fetch('/payments/marketplace/verify', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify({
        razorpay_order_id: checkoutResult.razorpay_order_id,
        razorpay_payment_id: checkoutResult.razorpay_payment_id,
        razorpay_signature: checkoutResult.razorpay_signature,
      }),
    })
    const verifyData = await verifyRes.json()
    if (verifyRes.ok && verifyData.status === 'success') {
      showToast.success(verifyData.message || 'Subscribed', 'strategy')
      fetchMarketplace()
    } else {
      showToast.error(verifyData.message || 'Payment verification failed', 'strategy')
    }
  }

  const handleSubscribe = async (item: CatalogItem) => {
    if (item.strategyId == null) {
      showToast.info(`${item.name} preview — publisher subscription coming soon`, 'strategy')
      return
    }
    const isSubbed = subscribed.has(item.strategyId)

    // Priced listings go through Razorpay checkout; unsubscribe and free
    // listings keep the direct subscribe/unsubscribe endpoint.
    if (!isSubbed && item.price && item.price > 0) {
      try {
        await subscribeWithPayment(item)
      } catch {
        showToast.error('Network error. Please try again.', 'strategy')
      }
      return
    }

    try {
      const res = await fetch(
        `/strategy/api/marketplace/${item.strategyId}/${isSubbed ? 'unsubscribe' : 'subscribe'}`,
        { method: 'POST' }
      )
      const data = await res.json()
      if (data.status === 'success') {
        showToast.success(data.message || 'Done', 'strategy')
        fetchMarketplace()
      } else {
        showToast.error(data.message || 'Operation failed', 'strategy')
      }
    } catch {
      showToast.error('Network error. Please try again.', 'strategy')
    }
  }

  const handlePrimary = (item: CatalogItem) => {
    if (item.tier === 'free' || item.tier === 'pro') {
      // Per CatalogItem's own doc comment (lib/marketplace-catalog.ts):
      // "Exactly one of these should be set for a template to be genuinely
      // wired" -- signalId identifies the real strategy TYPE,
      // optionsTemplateId opens the Options Strategy Builder.
      //
      // Users configuring these templates don't write/read code -- every
      // signalId item routes to the no-code wizard (/strategy/configure),
      // never to the Python-code review screen. services/strategy_compiler.py
      // currently has real compilers for 10 of the ~25 signalId types (ORB,
      // EMA Cross, RSI Momentum, SMA Cross, MACD Momentum, RSI Reversal,
      // Swing Breakout, ROC Momentum, Previous Day Breakout -- Supertrend and
      // Options Strategy blueprints exist but intentionally raise
      // CompilerError). Deploying an unsupported type fails with a clear
      // error message from the backend (surfaced by
      // StrategyConfigurator.tsx's deploy handler) rather than silently
      // no-op'ing or falling back to a different UI -- this is deliberate:
      // it keeps ALL template cards on one consistent no-code flow, with
      // "not supported yet" as a deploy-time error for the remaining types,
      // instead of routing some templates to a code-editing screen.
      if (item.optionsTemplateId) {
        navigate(`/visual-builder?template=${encodeURIComponent(item.id)}`)
      } else {
        navigate(`/strategy/configure?template=${encodeURIComponent(item.id)}`)
      }
      return
    }
    handleSubscribe(item)
  }

  const setTab = (tab: string) => {
    setActiveTab(tab as Tab)
    setCategory('all')
  }

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] overflow-hidden px-4 sm:px-6 py-3 space-y-3 max-w-7xl mx-auto">
      {/* Fixed Header & Controls */}
      <div className="shrink-0 space-y-3">
        {/* Tab strip */}
        <Tabs value={activeTab} onValueChange={setTab}>
          <TabsList className="w-full h-auto flex flex-wrap justify-start gap-1 p-1">
            {TAB_META.map((meta) => (
              <TabsTrigger
                key={meta.tab}
                value={meta.tab}
                className="text-xs font-semibold px-3 py-1.5"
              >
                {meta.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        {isTemplateTab && (
          <div className="grid grid-cols-3 gap-3">
            <StatCard label="Ready to Trade" value={templateStats.wired} icon={Zap} />
            <StatCard label="Total Templates" value={templateStats.total} icon={Layers} />
            <StatCard
              label="Coming Soon"
              value={templateStats.total - templateStats.wired}
              icon={Sparkles}
            />
          </div>
        )}

        {/* Search + category filters */}
        <div className="flex flex-col gap-2">
          <div className="flex flex-col sm:flex-row sm:items-center gap-2">
            <div className="relative w-full sm:w-72">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder="Search strategies..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-8 h-8 text-xs"
              />
            </div>
            {isTemplateTab && (
              <Button
                variant={wiredOnly ? 'default' : 'outline'}
                size="sm"
                className="h-8 text-xs w-fit"
                onClick={() => setWiredOnly((v) => !v)}
              >
                <Zap className="h-3.5 w-3.5 mr-1.5" />
                {wiredOnly ? 'Showing ready-to-trade only' : 'Show all (incl. coming soon)'}
              </Button>
            )}
          </div>
          {categories.length > 0 && (
            <div className="flex flex-wrap gap-1">
              <Button
                variant={category === 'all' ? 'default' : 'outline'}
                size="sm"
                className="h-6 text-[11px] px-2 py-0"
                onClick={() => setCategory('all')}
              >
                All
              </Button>
              {categories.map((c) => (
                <Button
                  key={c}
                  variant={category === c ? 'default' : 'outline'}
                  size="sm"
                  className="h-6 text-[11px] px-2 py-0"
                  onClick={() => setCategory(c)}
                >
                  {c}
                </Button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Scrollable Strategies Container */}
      <div className="flex-1 min-h-0 overflow-y-auto pr-1">
        {filtered.length === 0 ? (
          <div className="text-center py-12 border border-dashed rounded-xl space-y-2">
            <Layers className="h-8 w-8 text-muted-foreground/60 mx-auto" />
            <h3 className="text-sm font-bold">
              {activeTab === 'subscriptions' ? 'No active subscriptions' : 'No items found'}
            </h3>
            <p className="text-xs text-muted-foreground">
              {activeTab === 'subscriptions'
                ? 'Subscribe to a Premium strategy to see it here.'
                : 'Try a different search or category.'}
            </p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 pb-6">
            {filtered.map((item) => (
              <CatalogCard
                key={item.id}
                item={item}
                isSubscribed={item.strategyId != null && subscribed.has(item.strategyId)}
                onPrimary={handlePrimary}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
