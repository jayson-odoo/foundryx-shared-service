import { python } from '@codemirror/lang-python';
import { ensureSyntaxTree, syntaxTree } from '@codemirror/language';
import { EditorState } from '@codemirror/state';

/** Conservative parser diagnostics only. This is syntax feedback, not a
 * security/runtime guarantee; backend AST enforcement remains an S4 boundary. */
export function pythonSyntaxIssues(source: string): string[] {
  if (!source.trim()) return [];
  const state = EditorState.create({ doc: source, extensions: [python()] });
  const issues: string[] = [];
  // The Lezer parser is incremental: `syntaxTree` alone may hand back a
  // PARTIAL tree whose frontier reads as an error node (flaky "syntax error
  // on line 1"). Force a complete parse before inspecting it.
  const tree =
    ensureSyntaxTree(state, state.doc.length, 5_000) ?? syntaxTree(state);
  tree.iterate({
    enter(node) {
      if (!node.type.isError || issues.length > 0) return;
      issues.push(
        `Python syntax error on line ${state.doc.lineAt(node.from).number}.`,
      );
    },
  });
  return issues;
}
