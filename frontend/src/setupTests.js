import '@testing-library/jest-dom/vitest'

// jsdom implements neither of these, and both are used by the backdrop and the
// reduced-motion checks. Stubbing them here keeps every test file clean.
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })
}

if (!window.requestAnimationFrame) {
  window.requestAnimationFrame = (callback) => setTimeout(() => callback(Date.now()), 16)
  window.cancelAnimationFrame = (id) => clearTimeout(id)
}

// jsdom has no canvas implementation. RainCanvas already handles a null
// context, but stubbing getContext keeps the real drawing path exercised and
// keeps "not implemented" noise out of the test output.
if (typeof HTMLCanvasElement !== 'undefined') {
  HTMLCanvasElement.prototype.getContext = () => ({
    setTransform: () => {},
    clearRect: () => {},
    beginPath: () => {},
    moveTo: () => {},
    lineTo: () => {},
    stroke: () => {},
  })
}
