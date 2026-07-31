import { describe, expect, it } from 'vitest'
import { render, screen } from '@/test/test-utils'
import { PageLoader } from './page-loader'

describe('PageLoader', () => {
  it('renders the loading text', () => {
    render(<PageLoader />)

    // "Loading" is split from its ellipsis (the ellipsis pulses
    // independently), so match the stable prefix rather than the exact
    // full string.
    expect(screen.getByText(/Loading/)).toBeInTheDocument()
  })

  it('has correct styling classes', () => {
    const { container } = render(<PageLoader />)

    // Check main container has correct classes
    const mainDiv = container.firstChild as HTMLElement
    expect(mainDiv).toHaveClass('min-h-screen')
    expect(mainDiv).toHaveClass('flex')
    expect(mainDiv).toHaveClass('items-center')
    expect(mainDiv).toHaveClass('justify-center')
  })

  it('renders the animated brand arc', () => {
    const { container } = render(<PageLoader />)

    // The rotating brand-colored arc uses motion-safe:animate-spin so the
    // animation is suppressed under prefers-reduced-motion.
    const spinner = container.querySelector('.motion-safe\\:animate-spin')
    expect(spinner).toBeInTheDocument()
  })

  describe('accessibility', () => {
    it('has accessible loading indicator', () => {
      render(<PageLoader />)

      // Screen-reader-announceable text is present.
      expect(screen.getByText(/Loading/)).toBeInTheDocument()
    })
  })
})
