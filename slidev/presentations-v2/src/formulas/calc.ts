// Calculated fields: math.js, restricted. Loaded only when a chart has a calculated field or the editor's formula
// dialog opens (it is the biggest library).
//
// What is allowed: numbers, the names of the chart's fields, + - * / ^ %, brackets, and a short list of functions
// (safeDivide, abs, round, floor, ceil, min, max, sqrt, pow, log). Nothing else: no assignment, no strings, no
// arrays, no objects, no property access, no function definitions. The math.js instance has its dangerous functions
// (import, evaluate, parse, simplify, ...) switched off as well, as math.js's own security guide advises.
// A missing number or a division by zero gives null (an empty bar), never an error or Infinity.
import { all, create, type MathNode } from 'mathjs';

const math = create(all);
// Kept before they are switched off: this file parses a formula itself, then checks every node of it.
const parseFormula = math.parse.bind(math) as (text: string) => MathNode;
const OFF = ['import', 'createUnit', 'reviver', 'evaluate', 'parse', 'simplify', 'derivative', 'resolve', 'compile', 'parser', 'chain', 'help', 'rationalize', 'simplifyCore'];
math.import(Object.fromEntries(OFF.map(name => [name, () => { throw new Error(`${name} is not allowed`); }])), { override: true });

export const ALLOWED_FUNCTIONS = ['safeDivide', 'abs', 'round', 'floor', 'ceil', 'min', 'max', 'sqrt', 'pow', 'log'] as const;
const NODE_TYPES = new Set(['ConstantNode', 'SymbolNode', 'OperatorNode', 'FunctionNode', 'ParenthesisNode']);

/** a / b, or null when b is zero or either is missing (the helper for "rate" fields). */
export function safeDivide(a: unknown, b: unknown): number | null {
  const x = Number(a), y = Number(b);
  if (a == null || b == null || !Number.isFinite(x) || !Number.isFinite(y) || y === 0) return null;
  return x / y;
}

export class FormulaError extends Error {}

export type Row = Record<string, number | null | undefined>;
export interface Compiled {
  fields: string[]; // the field names the formula uses
  run(row: Row): number | null;
}

/** Compiles a formula once. Throws FormulaError (with a sentence) for a mistake or anything not allowed. */
export function compileFormula(formula: string, knownFields: string[]): Compiled {
  if (!formula.trim() || formula.length > 200) throw new FormulaError('Write a formula of at most 200 characters.');
  let tree: MathNode;
  try {
    tree = parseFormula(formula);
  } catch (error) {
    throw new FormulaError(`The formula cannot be read: ${(error as Error).message}`);
  }
  const used = new Set<string>();
  const fnSymbols = new Set<unknown>();
  tree.traverse((node: any) => {
    if (!NODE_TYPES.has(node.type)) throw new FormulaError('Only numbers, field names, + - * / ^ and a few functions are allowed.');
    if (node.type === 'ConstantNode' && typeof node.value !== 'number') throw new FormulaError('Only numbers are allowed, no text.');
    if (node.type === 'FunctionNode') {
      if (node.fn?.type !== 'SymbolNode' || !(ALLOWED_FUNCTIONS as readonly string[]).includes(node.fn.name)) {
        throw new FormulaError(`The function ${node.fn?.name ?? ''} is not allowed. Use ${ALLOWED_FUNCTIONS.join(', ')}.`);
      }
      fnSymbols.add(node.fn);
    }
  });
  tree.traverse((node: any) => {
    if (node.type === 'SymbolNode' && !fnSymbols.has(node)) {
      if (!knownFields.includes(node.name)) throw new FormulaError(`${node.name} is not a field of this chart. Fields: ${knownFields.join(', ')}.`);
      used.add(node.name);
    }
  });
  const code = tree.compile();
  const fields = [...used];
  return {
    fields,
    run(row) {
      const scope: Record<string, unknown> = { safeDivide };
      for (const f of fields) {
        const v = row[f];
        if (v == null || !Number.isFinite(v)) return null;
        scope[f] = v;
      }
      try {
        const result = code.evaluate(scope);
        return typeof result === 'number' && Number.isFinite(result) ? result : null;
      } catch {
        return null;
      }
    },
  };
}
