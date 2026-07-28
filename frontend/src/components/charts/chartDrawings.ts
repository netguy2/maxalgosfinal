// components/charts/chartDrawings.ts
// Manual chart drawing tools: Trendline, Horizontal Ray, Rectangle,
// Fibonacci Retracement. lightweight-charts v5 has no built-in drawing
// primitives — every shape must be hand-authored as an ISeriesPrimitive
// (paneViews -> IPrimitivePaneRenderer.draw() using raw canvas 2D calls).
// No click/drag interaction is provided by the library either; that's
// wired separately in LiveCandlestickChart.tsx via chart.subscribeClick().
// This file holds the framework-agnostic data types plus the primitive
// classes, kept out of LiveCandlestickChart.tsx so that file doesn't
// balloon.

import type { CanvasRenderingTarget2D } from 'fancy-canvas'
import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  PrimitiveHoveredItem,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from 'lightweight-charts'

export interface TrendlineDrawing {
  id: string
  type: 'trendline'
  pointA: { time: number; price: number }
  pointB: { time: number; price: number }
  color: string
}

export interface HorizontalRayDrawing {
  id: string
  type: 'horizontal_ray'
  point: { time: number; price: number }
  color: string
}

export interface RectangleDrawing {
  id: string
  type: 'rectangle'
  pointA: { time: number; price: number }
  pointB: { time: number; price: number }
  color: string
}

export interface FibonacciDrawing {
  id: string
  type: 'fibonacci'
  /** High anchor. */
  pointA: { time: number; price: number }
  /** Low anchor. */
  pointB: { time: number; price: number }
  color: string
}

export type ChartDrawing =
  | TrendlineDrawing
  | HorizontalRayDrawing
  | RectangleDrawing
  | FibonacciDrawing

const HIT_TEST_TOLERANCE_PX = 6
const FIB_RATIOS = [0, 0.236, 0.382, 0.5, 0.618, 1]
// Standard-ish fib level colors, distinguishable from each other rather
// than one flat color for every line — matches conventional fib UX on
// other charting platforms.
const FIB_COLORS = ['#787b86', '#f23645', '#ff9800', '#4caf50', '#089981', '#2962ff']

/** Perpendicular distance from point (px, py) to the segment (x1,y1)-(x2,y2), clamped to the segment. */
function distanceToSegment(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number
): number {
  const dx = x2 - x1
  const dy = y2 - y1
  const lengthSq = dx * dx + dy * dy
  if (lengthSq === 0) return Math.hypot(px - x1, py - y1)
  let t = ((px - x1) * dx + (py - y1) * dy) / lengthSq
  t = Math.max(0, Math.min(1, t))
  const projX = x1 + t * dx
  const projY = y1 + t * dy
  return Math.hypot(px - projX, py - projY)
}

function withAlpha(hexColor: string, alpha: number): string {
  const clamped = Math.max(0, Math.min(1, alpha))
  const alphaHex = Math.round(clamped * 255)
    .toString(16)
    .padStart(2, '0')
  return `${hexColor}${alphaHex}`
}

type LineCoords = { x1: number; y1: number; x2: number; y2: number }
type RectCoords = { x1: number; y1: number; x2: number; y2: number }
type FibLevel = { x1: number; x2: number; y: number; ratio: number; price: number }

// --- Renderers -----------------------------------------------------------
// Each renderer runs inside target.useMediaCoordinateSpace(({context}) =>
// ...) — a plain, unrestricted CanvasRenderingContext2D (confirmed against
// fancy-canvas's typings: fillRect/fill/fillText/strokeRect all work
// identically to stroke(), no primitive-specific gating). save()/restore()
// bracket every draw call so one drawing's style never bleeds into another.

class LineRenderer implements IPrimitivePaneRenderer {
  private readonly getLine: () => LineCoords | null
  private readonly color: string
  private readonly selected: boolean

  constructor(getLine: () => LineCoords | null, color: string, selected: boolean) {
    this.getLine = getLine
    this.color = color
    this.selected = selected
  }

  draw(target: CanvasRenderingTarget2D): void {
    const line = this.getLine()
    if (!line) return
    // biome-ignore lint/correctness/useHookAtTopLevel: fancy-canvas's CanvasRenderingTarget2D.useMediaCoordinateSpace is a plain method (not a React hook) — the "use" prefix is a naming coincidence.
    target.useMediaCoordinateSpace(({ context }: { context: CanvasRenderingContext2D }) => {
      context.save()
      context.strokeStyle = this.color
      context.lineWidth = this.selected ? 2.5 : 1.5
      context.setLineDash([])
      context.beginPath()
      context.moveTo(line.x1, line.y1)
      context.lineTo(line.x2, line.y2)
      context.stroke()
      context.restore()
    })
  }
}

class RectRenderer implements IPrimitivePaneRenderer {
  private readonly getRect: () => RectCoords | null
  private readonly color: string
  private readonly selected: boolean

  constructor(getRect: () => RectCoords | null, color: string, selected: boolean) {
    this.getRect = getRect
    this.color = color
    this.selected = selected
  }

  draw(target: CanvasRenderingTarget2D): void {
    const rect = this.getRect()
    if (!rect) return
    const x = Math.min(rect.x1, rect.x2)
    const y = Math.min(rect.y1, rect.y2)
    const width = Math.abs(rect.x2 - rect.x1)
    const height = Math.abs(rect.y2 - rect.y1)
    // biome-ignore lint/correctness/useHookAtTopLevel: fancy-canvas method, not a React hook — see LineRenderer above.
    target.useMediaCoordinateSpace(({ context }: { context: CanvasRenderingContext2D }) => {
      context.save()
      context.fillStyle = withAlpha(this.color, 0.15)
      context.fillRect(x, y, width, height)
      context.strokeStyle = this.color
      context.lineWidth = this.selected ? 2.5 : 1.5
      context.strokeRect(x, y, width, height)
      context.restore()
    })
  }
}

class FibRenderer implements IPrimitivePaneRenderer {
  private readonly getLevels: () => FibLevel[] | null

  constructor(getLevels: () => FibLevel[] | null) {
    this.getLevels = getLevels
  }

  draw(target: CanvasRenderingTarget2D): void {
    const levels = this.getLevels()
    if (!levels || levels.length === 0) return
    // biome-ignore lint/correctness/useHookAtTopLevel: fancy-canvas method, not a React hook — see LineRenderer above.
    target.useMediaCoordinateSpace(({ context }: { context: CanvasRenderingContext2D }) => {
      context.save()
      context.font = '11px sans-serif'
      context.textBaseline = 'middle'
      for (const level of levels) {
        const color = FIB_COLORS[FIB_RATIOS.indexOf(level.ratio)] ?? '#787b86'
        context.strokeStyle = color
        context.lineWidth = 1
        context.beginPath()
        context.moveTo(level.x1, level.y)
        context.lineTo(level.x2, level.y)
        context.stroke()
        context.fillStyle = color
        context.fillText(
          `${(level.ratio * 100).toFixed(1)}%  ${level.price.toFixed(2)}`,
          level.x2 + 4,
          level.y
        )
      }
      context.restore()
    })
  }
}

// --- Pane views ------------------------------------------------------------

class LinePaneView implements IPrimitivePaneView {
  private readonly getLine: () => LineCoords | null
  private readonly color: string
  private readonly selected: boolean

  constructor(getLine: () => LineCoords | null, color: string, selected: boolean) {
    this.getLine = getLine
    this.color = color
    this.selected = selected
  }

  renderer(): IPrimitivePaneRenderer {
    return new LineRenderer(this.getLine, this.color, this.selected)
  }
}

class RectPaneView implements IPrimitivePaneView {
  private readonly getRect: () => RectCoords | null
  private readonly color: string
  private readonly selected: boolean

  constructor(getRect: () => RectCoords | null, color: string, selected: boolean) {
    this.getRect = getRect
    this.color = color
    this.selected = selected
  }

  renderer(): IPrimitivePaneRenderer {
    return new RectRenderer(this.getRect, this.color, this.selected)
  }
}

class FibPaneView implements IPrimitivePaneView {
  private readonly getLevels: () => FibLevel[] | null

  constructor(getLevels: () => FibLevel[] | null) {
    this.getLevels = getLevels
  }

  renderer(): IPrimitivePaneRenderer {
    return new FibRenderer(this.getLevels)
  }
}

// --- Primitives --------------------------------------------------------

abstract class BaseDrawingPrimitive implements ISeriesPrimitive<Time> {
  protected chart: IChartApi | null = null
  protected series: ISeriesApi<'Candlestick'> | null = null
  protected requestUpdate: (() => void) | null = null
  public selected = false

  abstract readonly id: string
  abstract readonly color: string

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart
    this.series = param.series as ISeriesApi<'Candlestick'>
    this.requestUpdate = param.requestUpdate
  }

  detached(): void {
    this.chart = null
    this.series = null
    this.requestUpdate = null
  }

  abstract updateAllViews(): void
  abstract paneViews(): readonly IPrimitivePaneView[]
  abstract hitTest(x: number, y: number): PrimitiveHoveredItem | null
}

abstract class TwoPointLinePrimitive extends BaseDrawingPrimitive {
  protected cachedLine: LineCoords | null = null
  protected abstract computeLine(): LineCoords | null

  updateAllViews(): void {
    this.cachedLine = this.computeLine()
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [new LinePaneView(() => this.cachedLine, this.color, this.selected)]
  }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    const line = this.cachedLine
    if (!line) return null
    const dist = distanceToSegment(x, y, line.x1, line.y1, line.x2, line.y2)
    if (dist <= HIT_TEST_TOLERANCE_PX) {
      return { cursorStyle: 'pointer', externalId: this.id, zOrder: 'normal' }
    }
    return null
  }
}

export class TrendlinePrimitive extends TwoPointLinePrimitive {
  readonly id: string
  readonly color: string
  private pointA: { time: number; price: number }
  private pointB: { time: number; price: number }

  constructor(drawing: TrendlineDrawing) {
    super()
    this.id = drawing.id
    this.color = drawing.color
    this.pointA = drawing.pointA
    this.pointB = drawing.pointB
  }

  protected computeLine() {
    if (!this.series || !this.chart) return null
    const x1 = this.chart.timeScale().timeToCoordinate(this.pointA.time as UTCTimestamp)
    const y1 = this.series.priceToCoordinate(this.pointA.price)
    const x2 = this.chart.timeScale().timeToCoordinate(this.pointB.time as UTCTimestamp)
    const y2 = this.series.priceToCoordinate(this.pointB.price)
    if (x1 === null || y1 === null || x2 === null || y2 === null) return null
    return { x1, y1, x2, y2 }
  }
}

export class HorizontalRayPrimitive extends TwoPointLinePrimitive {
  readonly id: string
  readonly color: string
  private point: { time: number; price: number }

  constructor(drawing: HorizontalRayDrawing) {
    super()
    this.id = drawing.id
    this.color = drawing.color
    this.point = drawing.point
  }

  protected computeLine() {
    if (!this.series || !this.chart) return null
    const x1 = this.chart.timeScale().timeToCoordinate(this.point.time as UTCTimestamp)
    const y = this.series.priceToCoordinate(this.point.price)
    if (x1 === null || y === null) return null
    // Extend across the full visible pane width to the right edge, using
    // the time scale's own reported width rather than a hardcoded value
    // so it stays correct across window resizes.
    const width = this.chart.timeScale().width()
    return { x1, y1: y, x2: width, y2: y }
  }
}

export class RectanglePrimitive extends BaseDrawingPrimitive {
  readonly id: string
  readonly color: string
  private pointA: { time: number; price: number }
  private pointB: { time: number; price: number }
  private cachedRect: RectCoords | null = null

  constructor(drawing: RectangleDrawing) {
    super()
    this.id = drawing.id
    this.color = drawing.color
    this.pointA = drawing.pointA
    this.pointB = drawing.pointB
  }

  private computeRect(): RectCoords | null {
    if (!this.series || !this.chart) return null
    const x1 = this.chart.timeScale().timeToCoordinate(this.pointA.time as UTCTimestamp)
    const y1 = this.series.priceToCoordinate(this.pointA.price)
    const x2 = this.chart.timeScale().timeToCoordinate(this.pointB.time as UTCTimestamp)
    const y2 = this.series.priceToCoordinate(this.pointB.price)
    if (x1 === null || y1 === null || x2 === null || y2 === null) return null
    return { x1, y1, x2, y2 }
  }

  updateAllViews(): void {
    this.cachedRect = this.computeRect()
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [new RectPaneView(() => this.cachedRect, this.color, this.selected)]
  }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    const rect = this.cachedRect
    if (!rect) return null
    const left = Math.min(rect.x1, rect.x2)
    const right = Math.max(rect.x1, rect.x2)
    const top = Math.min(rect.y1, rect.y2)
    const bottom = Math.max(rect.y1, rect.y2)
    // Hit-test the border only (within tolerance), not the filled
    // interior — clicking inside an empty part of the zone shouldn't
    // steal a click meant for a candle/other drawing underneath it.
    const nearLeft = Math.abs(x - left) <= HIT_TEST_TOLERANCE_PX && y >= top && y <= bottom
    const nearRight = Math.abs(x - right) <= HIT_TEST_TOLERANCE_PX && y >= top && y <= bottom
    const nearTop = Math.abs(y - top) <= HIT_TEST_TOLERANCE_PX && x >= left && x <= right
    const nearBottom = Math.abs(y - bottom) <= HIT_TEST_TOLERANCE_PX && x >= left && x <= right
    if (nearLeft || nearRight || nearTop || nearBottom) {
      return { cursorStyle: 'pointer', externalId: this.id, zOrder: 'normal' }
    }
    return null
  }
}

export class FibonacciPrimitive extends BaseDrawingPrimitive {
  readonly id: string
  readonly color: string
  /** High anchor. */
  private pointA: { time: number; price: number }
  /** Low anchor. */
  private pointB: { time: number; price: number }
  private cachedLevels: FibLevel[] | null = null

  constructor(drawing: FibonacciDrawing) {
    super()
    this.id = drawing.id
    this.color = drawing.color
    this.pointA = drawing.pointA
    this.pointB = drawing.pointB
  }

  private computeLevels(): FibLevel[] | null {
    if (!this.series || !this.chart) return null
    const x1 = this.chart.timeScale().timeToCoordinate(this.pointA.time as UTCTimestamp)
    const x2 = this.chart.timeScale().timeToCoordinate(this.pointB.time as UTCTimestamp)
    if (x1 === null || x2 === null) return null

    const high = Math.max(this.pointA.price, this.pointB.price)
    const low = Math.min(this.pointA.price, this.pointB.price)
    const levels: FibLevel[] = []
    for (const ratio of FIB_RATIOS) {
      const price = high - (high - low) * ratio
      const y = this.series.priceToCoordinate(price)
      if (y === null) continue
      levels.push({ x1: Math.min(x1, x2), x2: Math.max(x1, x2), y, ratio, price })
    }
    return levels
  }

  updateAllViews(): void {
    this.cachedLevels = this.computeLevels()
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [new FibPaneView(() => this.cachedLevels)]
  }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    const levels = this.cachedLevels
    if (!levels) return null
    for (const level of levels) {
      if (
        y >= level.y - HIT_TEST_TOLERANCE_PX &&
        y <= level.y + HIT_TEST_TOLERANCE_PX &&
        x >= level.x1 &&
        x <= level.x2
      ) {
        return { cursorStyle: 'pointer', externalId: this.id, zOrder: 'normal' }
      }
    }
    return null
  }
}

/** Builds the right primitive instance for a persisted/in-progress drawing. */
export function createPrimitiveForDrawing(drawing: ChartDrawing): BaseDrawingPrimitive {
  switch (drawing.type) {
    case 'trendline':
      return new TrendlinePrimitive(drawing)
    case 'horizontal_ray':
      return new HorizontalRayPrimitive(drawing)
    case 'rectangle':
      return new RectanglePrimitive(drawing)
    case 'fibonacci':
      return new FibonacciPrimitive(drawing)
  }
}
