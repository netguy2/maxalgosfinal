import { describe, expect, it } from 'vitest'
import {
  bottomNavItems,
  isActiveRoute,
  mobileSheetItems,
  navItems,
  navSections,
  profileMenuItems,
} from './navigation'

describe('Navigation Config', () => {
  describe('navSections', () => {
    it('contains the expected sections', () => {
      const labels = navSections.map((section) => section.label)
      expect(labels).toEqual(['Trading', 'Strategies', 'Automation', 'Tools & Data', 'System'])
    })

    it('has no duplicate hrefs across sections', () => {
      const hrefs = navItems.map((item) => item.href)
      expect(new Set(hrefs).size).toBe(hrefs.length)
    })

    it('does not link legacy redirect routes', () => {
      const hrefs = navItems.map((item) => item.href)
      expect(hrefs).not.toContain('/strategybuilder')
      expect(hrefs).toContain('/visual-builder')
    })

    it('groups execution engines under Automation, registry views under Strategies', () => {
      const strategies = navSections.find((s) => s.label === 'Strategies')
      const automation = navSections.find((s) => s.label === 'Automation')
      expect(strategies?.items.map((i) => i.href)).toEqual([
        '/strategy',
        '/marketplace',
        '/deployments',
        '/analytics',
      ])
      expect(automation?.items.map((i) => i.href)).toEqual([
        '/visual-builder',
        '/python',
        '/flow',
        '/maxhook',
      ])
    })
  })

  describe('navItems', () => {
    it('is the flattened list of all section items', () => {
      const sectionCount = navSections.reduce((sum, s) => sum + s.items.length, 0)
      expect(navItems).toHaveLength(sectionCount)

      const labels = navItems.map((item) => item.label)
      expect(labels).toContain('Dashboard')
      expect(labels).toContain('Options Tools')
      expect(labels).toContain('Orderbook')
      expect(labels).toContain('Positions')
      expect(labels).toContain('My Strategies')
      expect(labels).toContain('Marketplace')
    })

    it('all items have required properties', () => {
      navItems.forEach((item) => {
        expect(item).toHaveProperty('href')
        expect(item).toHaveProperty('label')
        expect(item).toHaveProperty('icon')
        expect(item.href).toMatch(/^\//)
        expect(item.label.length).toBeGreaterThan(0)
      })
    })
  })

  describe('bottomNavItems', () => {
    it('contains exactly 5 items for mobile bottom nav', () => {
      expect(bottomNavItems).toHaveLength(5)
    })

    it('has the correct order: Dashboard, Strategies, Marketplace, Deployments, Positions', () => {
      const labels = bottomNavItems.map((item) => item.label)
      expect(labels).toEqual(['Dashboard', 'Strategies', 'Marketplace', 'Deployments', 'Positions'])
    })
  })

  describe('mobileSheetItems', () => {
    it('excludes items already in bottomNavItems', () => {
      const bottomPaths = bottomNavItems.map((item) => item.href)
      const sheetPaths = mobileSheetItems.map((item) => item.href)

      sheetPaths.forEach((path) => {
        expect(bottomPaths).not.toContain(path)
      })
    })

    it('contains remaining nav items', () => {
      const sheetLabels = mobileSheetItems.map((item) => item.label)
      expect(sheetLabels).toContain('Control Center')
      expect(sheetLabels).toContain('Options Tools')
      expect(sheetLabels).toContain('Logs')
    })
  })

  describe('profileMenuItems', () => {
    it('contains profile-related menu items', () => {
      const labels = profileMenuItems.map((item) => item.label)
      expect(labels).toContain('Profile')
      expect(labels).toContain('Holdings')
    })
  })

  describe('isActiveRoute', () => {
    it('returns true for exact matches', () => {
      expect(isActiveRoute('/dashboard', '/dashboard')).toBe(true)
      expect(isActiveRoute('/orderbook', '/orderbook')).toBe(true)
      expect(isActiveRoute('/positions', '/positions')).toBe(true)
    })

    it('returns false for non-matching routes', () => {
      expect(isActiveRoute('/dashboard', '/orderbook')).toBe(false)
      expect(isActiveRoute('/positions', '/holdings')).toBe(false)
    })

    it('prefix-matches nested pages at segment boundaries', () => {
      expect(isActiveRoute('/strategy', '/strategy')).toBe(true)
      expect(isActiveRoute('/strategy/new', '/strategy')).toBe(true)
      expect(isActiveRoute('/strategy/123/configure', '/strategy')).toBe(true)
      expect(isActiveRoute('/python/guide', '/python')).toBe(true)
      expect(isActiveRoute('/logs/live', '/logs')).toBe(true)
      expect(isActiveRoute('/sandbox/mypnl', '/sandbox')).toBe(true)
    })

    it('does not match partial path segments', () => {
      expect(isActiveRoute('/strategybuilder', '/strategy')).toBe(false)
      expect(isActiveRoute('/orderbookextra', '/orderbook')).toBe(false)
    })

    it('root path only matches exactly', () => {
      expect(isActiveRoute('/', '/')).toBe(true)
      expect(isActiveRoute('/dashboard', '/')).toBe(false)
    })
  })
})
