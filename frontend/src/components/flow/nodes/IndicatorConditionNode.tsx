/**
 * Indicator Condition Node
 * Gate a chain on a real technical indicator (RSI, EMA, SMA, MACD, ATR, VWAP)
 * computed from historical candle data, rather than raw price.
 */

import { Handle, Position } from '@xyflow/react'
import { Activity } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { IndicatorConditionNodeData } from '@/types/flow'

interface IndicatorConditionNodeProps {
  data: IndicatorConditionNodeData
  selected?: boolean
}

const operatorLabels: Record<string, string> = {
  '>': '>',
  '<': '<',
  '==': '=',
  '>=': '>=',
  '<=': '<=',
  '!=': '!=',
}

export const IndicatorConditionNode = memo(({ data, selected }: IndicatorConditionNodeProps) => {
  return (
    <div className={cn('workflow-node node-condition min-w-[120px]', selected && 'selected')}>
      <Handle
        type="target"
        position={Position.Top}
        className="!top-0 !-translate-y-1/2 !h-3 !w-3 !rounded-full !border-2 !border-background !bg-muted-foreground"
      />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded">
            <Activity className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Indicator</div>
            <div className="text-[9px] text-muted-foreground">Condition</div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Symbol</span>
            <span className="mono-data text-[10px] font-medium">{data.symbol || '-'}</span>
          </div>
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Check</span>
            <span className="text-[10px] font-medium">
              {data.indicator || 'RSI'}
              {data.indicator !== 'VWAP' ? `(${data.period ?? 14})` : ''}{' '}
              {operatorLabels[data.operator] || '<'} {data.value ?? 0}
            </span>
          </div>
        </div>
        {/* Handle labels */}
        <div className="mt-2 flex justify-between px-1 text-[8px]">
          <span className="text-buy">True</span>
          <span className="text-sell">False</span>
        </div>
      </div>
      {/* True output (left) - Condition met */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="true"
        className="!bottom-0 !translate-y-1/2 !bg-buy !h-3 !w-3 !rounded-full !border-2 !border-background"
        style={{ left: '25%' }}
      />
      {/* False output (right) - Condition not met */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="false"
        className="!bottom-0 !translate-y-1/2 !bg-sell !h-3 !w-3 !rounded-full !border-2 !border-background"
        style={{ left: '75%' }}
      />
    </div>
  )
})

IndicatorConditionNode.displayName = 'IndicatorConditionNode'
