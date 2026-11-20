/**
 * Turn `import.meta.glob` results into a registry: one named export per file,
 * unique ids. Pure, so the rules are testable without the real modules.
 *
 * @param modules - Path to module, as `import.meta.glob(..., { eager: true })` returns it.
 * @param exportName - The export each file must have (`objectType`, `tab`, …).
 * @param idOf - The entry's id.
 * @returns Entries in path order.
 * @throws Error naming the file when an export is missing or an id is taken.
 */
export function collect<T>(
  modules: Record<string, Record<string, unknown>>,
  exportName: string,
  idOf: (entry: T) => string,
): T[] {
  const seen = new Map<string, string>();
  return Object.keys(modules)
    .sort()
    .map((path) => {
      const entry = modules[path]?.[exportName] as T | undefined;
      if (entry === undefined) {
        throw new Error(`${path} must export \`${exportName}\``);
      }
      const id = idOf(entry);
      const other = seen.get(id);
      if (other !== undefined) {
        throw new Error(`${path} registers "${id}", already registered by ${other}`);
      }
      seen.set(id, path);
      return entry;
    });
}
