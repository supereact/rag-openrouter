import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// JSDOM does not implement layout-driven scrolling.
Object.defineProperty(Element.prototype, 'scrollIntoView', {
  configurable: true,
  value: vi.fn(),
})
