import { BookOpen } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DOC_LINKS, externalLinks } from '@/config/navigation'

interface DocsLinkProps {
  /** Key into config/navigation.ts's DOC_LINKS map, e.g. "sandbox", "option-chain". */
  page: string
  /** Compact icon-only button instead of the default icon + "Docs" label. */
  iconOnly?: boolean
  className?: string
}

/**
 * Shared "Docs" link/button for page headers. Resolves its href from the
 * single DOC_LINKS config map (config/navigation.ts) rather than each page
 * hand-writing its own docs.maxalgos.in URL -- so every page's doc link can
 * be corrected in one place once a specific deep-link anchor is confirmed
 * to resolve on the live site, instead of being scattered across ~20
 * one-off <a> tags with no shared source of truth.
 *
 * Falls back to the verified docs.maxalgos.in root for any page key not
 * yet in DOC_LINKS, so a missing entry never produces a dead/undefined href.
 */
export function DocsLink({ page, iconOnly = false, className }: DocsLinkProps) {
  const href = DOC_LINKS[page] ?? externalLinks.docs.href

  return (
    <Button variant="outline" size={iconOnly ? 'icon' : 'sm'} asChild className={className}>
      <a href={href} target="_blank" rel="noopener noreferrer" aria-label="View documentation">
        <BookOpen className="h-4 w-4" />
        {!iconOnly && <span className="ml-2">Docs</span>}
      </a>
    </Button>
  )
}
