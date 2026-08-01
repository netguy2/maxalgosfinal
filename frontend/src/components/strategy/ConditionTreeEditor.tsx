import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

// Mirrors services/condition_engine.py::evaluate_conditions_tree's node
// shapes exactly -- a GroupNode ("operator"/"children") or a LeafNode (an
// indicator comparison). The tree this editor produces/consumes IS the
// executable shape (see services/condition_tree_validator.py), not an
// intermediate representation that gets compiled later.
export type ConditionNode = GroupNode | LeafNode

export interface GroupNode {
  operator: 'AND' | 'OR'
  children: ConditionNode[]
}

export interface LeafNode {
  indicator: string
  condition: '>' | '<' | '>=' | '<=' | '==' | '!='
  value?: number
  value_indicator?: string
  value_indicator_params?: Record<string, number>
  period?: number
  interval?: string
  [key: string]: unknown
}

export interface IndicatorOption {
  name: string
  inputs: string[]
}

const COMPARISON_OPERATORS = ['>', '<', '>=', '<=', '==', '!='] as const

function isGroupNode(node: ConditionNode): node is GroupNode {
  return 'operator' in node
}

function defaultLeaf(indicators: IndicatorOption[]): LeafNode {
  const first = indicators[0]?.name ?? 'SPOT'
  return { indicator: first, condition: '>', value: 0 }
}

interface LeafRowProps {
  leaf: LeafNode
  indicators: IndicatorOption[]
  onChange: (leaf: LeafNode) => void
  onDelete: () => void
}

function IndicatorLeafRow({ leaf, indicators, onChange, onDelete }: LeafRowProps) {
  const inputsFor = (name: string) => indicators.find((i) => i.name === name)?.inputs ?? []
  // Derived from the leaf itself, not local state -- the leaf's own shape
  // (value vs value_indicator present) is the single source of truth,
  // matching this editor's fully-controlled design.
  const useValueIndicator = Boolean(leaf.value_indicator)

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-border/60 bg-muted/30 p-2">
      <Select value={leaf.indicator} onValueChange={(v) => onChange({ ...leaf, indicator: v })}>
        <SelectTrigger className="w-[140px]" size="sm">
          <SelectValue placeholder="Indicator" />
        </SelectTrigger>
        <SelectContent>
          {indicators.map((ind) => (
            <SelectItem key={ind.name} value={ind.name}>
              {ind.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {inputsFor(leaf.indicator).includes('period') && (
        <Input
          type="number"
          className="w-20"
          placeholder="period"
          value={leaf.period ?? ''}
          onChange={(e) => onChange({ ...leaf, period: Number(e.target.value) || undefined })}
        />
      )}

      <Select
        value={leaf.condition}
        onValueChange={(v) => onChange({ ...leaf, condition: v as LeafNode['condition'] })}
      >
        <SelectTrigger className="w-[80px]" size="sm">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {COMPARISON_OPERATORS.map((op) => (
            <SelectItem key={op} value={op}>
              {op}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {useValueIndicator ? (
        <Select
          value={leaf.value_indicator}
          onValueChange={(v) => onChange({ ...leaf, value_indicator: v, value: undefined })}
        >
          <SelectTrigger className="w-[140px]" size="sm">
            <SelectValue placeholder="Compare to indicator" />
          </SelectTrigger>
          <SelectContent>
            {indicators.map((ind) => (
              <SelectItem key={ind.name} value={ind.name}>
                {ind.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <Input
          type="number"
          className="w-24"
          placeholder="value"
          value={leaf.value ?? ''}
          onChange={(e) => onChange({ ...leaf, value: Number(e.target.value) })}
        />
      )}

      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() =>
          onChange(
            useValueIndicator
              ? { ...leaf, value_indicator: undefined, value_indicator_params: undefined, value: 0 }
              : { ...leaf, value: undefined, value_indicator: indicators[0]?.name ?? 'EMA' }
          )
        }
        title="Compare against another indicator instead of a fixed number"
      >
        {useValueIndicator ? 'Use fixed value' : 'Compare to indicator'}
      </Button>

      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="ml-auto text-destructive"
        onClick={onDelete}
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  )
}

interface ConditionTreeEditorProps {
  value: GroupNode
  onChange: (value: GroupNode) => void
  indicators: IndicatorOption[]
  depth?: number
}

/** Recursive AND/OR condition-tree editor. Fully controlled
 * (value/onChange over the exact JSON shape services/condition_tree_validator.py
 * validates and services/condition_engine.py interprets) -- has no
 * backend awareness of its own. */
export function ConditionTreeEditor({
  value,
  onChange,
  indicators,
  depth = 0,
}: ConditionTreeEditorProps) {
  const updateChild = (index: number, child: ConditionNode) => {
    const children = [...value.children]
    children[index] = child
    onChange({ ...value, children })
  }

  const deleteChild = (index: number) => {
    onChange({ ...value, children: value.children.filter((_, i) => i !== index) })
  }

  const addCondition = () => {
    onChange({ ...value, children: [...value.children, defaultLeaf(indicators)] })
  }

  const addGroup = () => {
    onChange({
      ...value,
      children: [...value.children, { operator: 'AND', children: [defaultLeaf(indicators)] }],
    })
  }

  return (
    <div
      className={
        depth === 0
          ? 'space-y-2'
          : 'space-y-2 rounded-md border border-dashed border-border p-2 pl-3'
      }
    >
      <div className="flex items-center gap-2">
        <Select
          value={value.operator}
          onValueChange={(v) => onChange({ ...value, operator: v as 'AND' | 'OR' })}
        >
          <SelectTrigger className="w-[90px]" size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="AND">AND</SelectItem>
            <SelectItem value="OR">OR</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">of the following must be true:</span>
      </div>

      {value.children.map((child, i) =>
        isGroupNode(child) ? (
          <div key={i} className="flex items-start gap-2">
            <div className="flex-1">
              <ConditionTreeEditor
                value={child}
                onChange={(c) => updateChild(i, c)}
                indicators={indicators}
                depth={depth + 1}
              />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="text-destructive"
              onClick={() => deleteChild(i)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ) : (
          <IndicatorLeafRow
            key={i}
            leaf={child}
            indicators={indicators}
            onChange={(l) => updateChild(i, l)}
            onDelete={() => deleteChild(i)}
          />
        )
      )}

      <div className="flex gap-2">
        <Button type="button" variant="outline" size="sm" onClick={addCondition}>
          <Plus className="h-3.5 w-3.5 mr-1" /> Add Condition
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={addGroup}>
          <Plus className="h-3.5 w-3.5 mr-1" /> Add Group
        </Button>
      </div>
    </div>
  )
}
