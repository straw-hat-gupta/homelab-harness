import "@testing-library/jest-dom/vitest";

// jsdom lacks the layout APIs cmdk and Radix touch; these stand-ins are inert.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver = ResizeObserverStub;
Element.prototype.scrollIntoView = function scrollIntoView() {};
window.scrollTo = () => undefined;
window.matchMedia = (query: string) =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
