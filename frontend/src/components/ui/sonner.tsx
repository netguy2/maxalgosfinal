import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from 'lucide-react'
import { Toaster as Sonner, type ToasterProps } from 'sonner'
import { useThemeStore } from '@/stores/themeStore'

const Toaster = ({ ...props }: ToasterProps) => {
  const mode = useThemeStore((state) => state.mode)
  const appMode = useThemeStore((state) => state.appMode)
  // Analyzer mode is always a dark surface regardless of light/dark setting
  const theme: ToasterProps['theme'] = appMode === 'analyzer' ? 'dark' : mode

  return (
    <Sonner
      theme={theme}
      className="toaster group"
      offset="64px"
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          '--normal-bg': 'var(--popover)',
          '--normal-text': 'var(--popover-foreground)',
          '--normal-border': 'var(--border)',
          // sonner's error/success/warning/info toast variants each read
          // their own separate --error-bg/--success-bg/etc. vars, not
          // --normal-bg -- without setting these, error toasts (e.g. order
          // rejections) fell back to sonner's own built-in near-black
          // dark-mode default instead of the app's actual destructive/
          // success/warning/info theme tokens.
          '--error-bg': 'var(--destructive)',
          '--error-text': 'var(--destructive-foreground)',
          '--error-border': 'var(--destructive)',
          '--success-bg': 'var(--success)',
          '--success-text': 'var(--success-foreground)',
          '--success-border': 'var(--success)',
          '--warning-bg': 'var(--warning)',
          '--warning-text': 'var(--warning-foreground)',
          '--warning-border': 'var(--warning)',
          '--info-bg': 'var(--info)',
          '--info-text': 'var(--info-foreground)',
          '--info-border': 'var(--info)',
          '--border-radius': 'var(--radius)',
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
