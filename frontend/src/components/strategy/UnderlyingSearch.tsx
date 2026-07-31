import { Search } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { SymbolSearchResult } from '@/types/strategy'

interface Props {
  /** Current query / selected symbol (they share one field, as the original
   * inline control did — typing replaces the selection). */
  value: string
  onValueChange: (value: string) => void
  open: boolean
  onOpenChange: (open: boolean) => void
  results: SymbolSearchResult[]
  loading: boolean
  onSelect: (result: SymbolSearchResult) => void
  placeholder?: string
  searchPlaceholder?: string
}

/**
 * Symbol / underlying picker.
 *
 * Extracted verbatim from the inline block that lived inside the Add
 * Symbols form so the setup card can render the REAL control rather than a
 * button that scrolls you somewhere else to find it. Same Popover, same
 * combobox trigger, same result rows with the exchange badge — only the
 * location changed.
 *
 * State stays owned by the parent (the page already runs the debounced
 * search against `form.underlying` / `form.symbolSearch`), so this is a
 * presentational component with no fetching of its own.
 */
export function UnderlyingSearch({
  value,
  onValueChange,
  open,
  onOpenChange,
  results,
  loading,
  onSelect,
  placeholder = 'Search underlying...',
  searchPlaceholder = 'Search underlying (e.g. NIFTY, RELIANCE)...',
}: Props) {
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="w-full justify-between font-normal"
        >
          <span className={value ? '' : 'text-muted-foreground'}>{value || placeholder}</span>
          <Search className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[320px] p-2" align="start">
        <div className="flex items-center gap-2 border-b px-1 pb-2">
          <Search className="h-4 w-4 shrink-0 opacity-50" />
          <input
            // biome-ignore lint/a11y/noAutofocus: focusing the field is the entire point of opening a search popover
            autoFocus
            className="flex h-8 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            placeholder={searchPlaceholder}
            value={value}
            onChange={(e) => onValueChange(e.target.value.toUpperCase())}
            aria-label="Search symbols"
          />
        </div>
        <div className="max-h-[260px] space-y-1 overflow-y-auto pt-2">
          {loading ? (
            <div className="py-4 text-center text-xs text-muted-foreground">Searching...</div>
          ) : value.length < 2 ? (
            <div className="py-4 text-center text-xs text-muted-foreground">
              Type at least 2 characters...
            </div>
          ) : results.length === 0 ? (
            <div className="py-4 text-center text-xs text-muted-foreground">No symbols found</div>
          ) : (
            results.map((result) => (
              <button
                key={`${result.symbol}-${result.exchange}`}
                type="button"
                onClick={() => onSelect(result)}
                className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                <div className="flex min-w-0 flex-col">
                  <span className="truncate font-medium">{result.symbol}</span>
                  <span className="truncate text-xs text-muted-foreground">
                    {result.name || result.symbol}
                  </span>
                </div>
                <Badge variant="outline" className="ml-2 shrink-0 px-1 py-0 font-mono text-[10px]">
                  {result.exchange}
                </Badge>
              </button>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}
