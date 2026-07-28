/**
 * Basket P&L Check Node ("Master SL / Target")
 * Checks COMBINED P&L across a list of positions, not a single symbol.
 */

import { Handle, Position } from '@xyflow/react'
import { Target } from 'lucide-react'
import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { BasketPnlCheckNodeData } from '@/types/flow'

interface BasketPnlCheckNodeProps {
  data: BasketPnlCheckNodeData
  selected?: boolean
}

const conditionLabels: Record<string, string> = {
  pnl_above: 'Combined P&L Above',
  pnl_below: 'Combined P&L Below',
}

export const BasketPnlCheckNode = memo(({ data, selected }: BasketPnlCheckNodeProps) => {
  const symbolCount = (data.symbols || '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean).length

  return (
    <div className={cn('workflow-node node-condition min-w-[130px]', selected && 'selected')}>
      <Handle
        type="target"
        position={Position.Top}
        className="!top-0 !-translate-y-1/2 !h-3 !w-3 !rounded-full !border-2 !border-background !bg-muted-foreground"
      />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded">
            <Target className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Master SL / Target</div>
            <div className="text-[9px] text-muted-foreground">Basket P&L</div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Basket</span>
            <span className="mono-data text-[10px] font-medium">
              {symbolCount > 0 ? `${symbolCount} symbol${symbolCount === 1 ? '' : 's'}` : '-'}
            </span>
          </div>
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Check</span>
            <span className="text-[10px] font-medium">
              {conditionLabels[data.condition] || data.condition}
            </span>
          </div>
          <div className="flex items-center justify-between text-[9px] text-muted-foreground">
            <span>Threshold:</span>
            <span className="mono-data">{data.threshold ?? 0}</span>
          </div>
        </div>
        {/* Handle labels */}
        <div className="mt-2 flex justify-between px-1 text-[8px]">
          <span className="text-buy">True</span>
          <span className="text-sell">False</span>
        </div>
      </div>
      {/* True output (left) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="true"
        className="!bottom-0 !translate-y-1/2 !bg-buy !h-3 !w-3 !rounded-full !border-2 !border-background"
        style={{ left: '25%' }}
      />
      {/* False output (right) */}
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

BasketPnlCheckNode.displayName = 'BasketPnlCheckNode'
