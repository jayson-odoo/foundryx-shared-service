import { python } from '@codemirror/lang-python';
import { syntaxTree } from '@codemirror/language';
import { EditorState } from '@codemirror/state';

/** Conservative parser diagnostics only. This is syntax feedback, not a
 * security/runtime guarantee; backend AST enforcement remains an S4 boundary. */
export function pythonSyntaxIssues(source: string): string[] {
  if (!source.trim()) return [];
  const state = EditorState.create({ doc: source, extensions: [python()] });
  const issues: string[] = [];
  syntaxTree(state).iterate({
    enter(node) {
      if (!node.type.isError || issues.length > 0) return;
      issues.push(
        `Python syntax error on line ${state.doc.lineAt(node.from).number}.`,
      );
    },
  });
  return issues;
}
