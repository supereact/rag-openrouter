import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// JSDOM does not implement layout-driven scrolling.
Object.defineProperty(Element.prototype, 'scrollIntoView', {
  configurable: true,
  value: vi.fn(),
})

// Visibility is supplied by the browser in production. Keep observers inert in
// JSDOM; landing-page tests explicitly exercise visible/hidden motion states.
Object.defineProperty(globalThis, 'IntersectionObserver', {
  configurable: true,
  writable: true,
  value: class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
})
