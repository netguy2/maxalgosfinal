import { describe, expect, it } from 'vitest'
import {
  candleSeriesOptions,
  getChartTheme,
  lightweightChartsOptions,
  plotlyLayout,
} from './chart-theme'

describe('chart-theme', () => {
  it('getChartTheme returns every token key', () => {
    const theme = getChartTheme()
    expect(theme).toHaveProperty('background')
    expect(theme).toHaveProperty('profit')
    expect(theme).toHaveProperty('loss')
    expect(theme).toHaveProperty('buy')
    expect(theme).toHaveProperty('sell')
    expect(theme).toHaveProperty('brand')
    expect(theme.colorway).toHaveLength(5)
  })

  it('plotlyLayout wires theme colors into layout fields', () => {
    const theme = getChartTheme()
    const layout = plotlyLayout(theme) as Record<string, any>
    expect(layout.colorway).toEqual(theme.colorway)
    expect(layout.font.color).toBe(theme.mutedForeground)
    expect(layout.xaxis.gridcolor).toBe(theme.border)
  })

  it('lightweightChartsOptions wires theme colors', () => {
    const theme = getChartTheme()
    const opts = lightweightChartsOptions(theme) as Record<string, any>
    expect(opts.layout.textColor).toBe(theme.mutedForeground)
    expect(opts.grid.vertLines.color).toBe(theme.border)
  })

  it('candleSeriesOptions uses profit/loss for up/down', () => {
    const theme = getChartTheme()
    const opts = candleSeriesOptions(theme) as Record<string, any>
    expect(opts.upColor).toBe(theme.profit)
    expect(opts.downColor).toBe(theme.loss)
  })
})
