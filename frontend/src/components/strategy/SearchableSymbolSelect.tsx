import React, { useState, useMemo, useRef, useEffect } from 'react'
import { Check, ChevronsUpDown, Search, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { SYMBOL_OPTIONS } from '@/lib/symbol-options'
import { cn } from '@/lib/utils'

export interface SymbolOption {
  value: string
  label: string
  exchange: string
}

interface SearchableSymbolSelectProps {
  value: string
  onChange: (value: string) => void
  options?: SymbolOption[]
  className?: string
  placeholder?: string
  disabled?: boolean
}

export function SearchableSymbolSelect({
  value,
  onChange,
  options = SYMBOL_OPTIONS,
  className,
  placeholder = 'Select symbol...',
  disabled = false,
}: SearchableSymbolSelectProps) {
  const [open, setOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const selectedOption = useMemo(() => {
    return (
      options.find((opt) => opt.value === value) || {
        value,
        label: value || placeholder,
        exchange: 'NSE_INDEX',
      }
    )
  }, [options, value, placeholder])

  const filteredOptions = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return options
    return options.filter(
      (opt) =>
        opt.label.toLowerCase().includes(q) ||
        opt.value.toLowerCase().includes(q) ||
        opt.exchange.toLowerCase().includes(q)
    )
  }, [options, searchQuery])

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50)
    } else {
      setSearchQuery('')
    }
  }, [open])

  const handleSelect = (val: string) => {
    onChange(val)
    setOpen(false)
    setSearchQuery('')
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (filteredOptions.length > 0) {
        handleSelect(filteredOptions[0].value)
      } else if (searchQuery.trim()) {
        handleSelect(searchQuery.trim().toUpperCase())
      }
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild disabled={disabled}>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn(
            'w-full justify-between px-3 py-2 h-9 border-border bg-background text-xs font-bold hover:bg-accent hover:text-accent-foreground',
            className
          )}
        >
          <div className="flex items-center gap-2 truncate">
            <Search className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            <span className="truncate">{selectedOption.label}</span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0 ml-2">
            {selectedOption.exchange && (
              <Badge variant="secondary" className="px-1.5 py-0 text-[10px] font-mono font-normal">
                {selectedOption.exchange}
              </Badge>
            )}
            <ChevronsUpDown className="h-3.5 w-3.5 opacity-50 shrink-0" />
          </div>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[320px] p-2 bg-popover border-border shadow-md" align="start">
        <div className="flex items-center gap-2 border-b border-border px-2 pb-2">
          <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
          <input
            ref={inputRef}
            type="text"
            className="flex h-8 w-full bg-transparent text-xs font-medium outline-none placeholder:text-muted-foreground"
            placeholder="Search symbol (e.g. NIFTY, GOLD, INFY)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              className="text-muted-foreground hover:text-foreground p-0.5"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <div className="max-h-[240px] space-y-1 overflow-y-auto pt-2">
          {filteredOptions.length === 0 ? (
            <div className="py-4 text-center text-xs text-muted-foreground">
              No matching symbol found
              {searchQuery.trim() && (
                <div className="mt-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-xs h-7 text-primary"
                    onClick={() => handleSelect(searchQuery.trim().toUpperCase())}
                  >
                    Use &quot;{searchQuery.trim().toUpperCase()}&quot; as symbol
                  </Button>
                </div>
              )}
            </div>
          ) : (
            filteredOptions.map((opt) => {
              const isSelected = opt.value === value
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => handleSelect(opt.value)}
                  className={cn(
                    'flex w-full items-center justify-between rounded px-2.5 py-1.5 text-left text-xs transition-colors hover:bg-accent hover:text-accent-foreground',
                    isSelected && 'bg-accent/60 font-semibold'
                  )}
                >
                  <div className="flex items-center gap-2 truncate">
                    <Check
                      className={cn(
                        'h-3.5 w-3.5 shrink-0 text-emerald-500',
                        isSelected ? 'opacity-100' : 'opacity-0'
                      )}
                    />
                    <div className="flex flex-col truncate">
                      <span className="font-bold text-xs">{opt.label}</span>
                      {opt.label !== opt.value && (
                        <span className="text-[10px] text-muted-foreground font-mono">{opt.value}</span>
                      )}
                    </div>
                  </div>
                  <Badge
                    variant="outline"
                    className="ml-2 shrink-0 px-1.5 py-0 text-[10px] font-mono font-normal"
                  >
                    {opt.exchange}
                  </Badge>
                </button>
              )
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}
