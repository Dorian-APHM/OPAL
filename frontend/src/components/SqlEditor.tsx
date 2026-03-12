import { useRef, useEffect, useCallback } from 'react';
import { EditorView, keymap, placeholder as cmPlaceholder, lineNumbers, highlightActiveLineGutter, highlightActiveLine, drawSelection, rectangularSelection, crosshairCursor, dropCursor } from '@codemirror/view';
import { EditorState, Compartment } from '@codemirror/state';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import { sql, PostgreSQL, type SQLConfig } from '@codemirror/lang-sql';
import { autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete';
import { searchKeymap, highlightSelectionMatches } from '@codemirror/search';
import {
  syntaxHighlighting,
  HighlightStyle,
  bracketMatching,
  foldGutter,
  foldKeymap,
  indentOnInput,
} from '@codemirror/language';
import { tags } from '@lezer/highlight';

interface SqlEditorProps {
  value: string;
  onChange: (value: string) => void;
  onExecute?: () => void;
  schema?: Record<string, string[]>;
  schemaName?: string;
  darkMode?: boolean;
  height?: string;
  placeholder?: string;
}

// ── Custom dark theme (always dark for SQL editor — better readability) ──
const opalDarkTheme = EditorView.theme(
  {
    '&': {
      backgroundColor: '#1e1e2e',
      color: '#cdd6f4',
      fontSize: '13px',
      borderRadius: '8px',
      overflow: 'hidden',
      border: '1px solid #313244',
    },
    '&.cm-focused': {
      outline: 'none',
      borderColor: '#1f77b4',
      boxShadow: '0 0 0 2px rgba(31, 119, 180, 0.25)',
    },
    '.cm-scroller': {
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace",
      overflow: 'auto',
      lineHeight: '1.6',
    },
    '.cm-content': {
      padding: '8px 0',
      caretColor: '#f5e0dc',
    },
    '.cm-cursor, .cm-dropCursor': {
      borderLeftColor: '#f5e0dc',
      borderLeftWidth: '2px',
    },
    '.cm-selectionBackground, .cm-content ::selection': {
      backgroundColor: '#45475a !important',
    },
    '.cm-activeLine': {
      backgroundColor: '#1e1e2e00', // transparent — no highlight on active line
    },
    '.cm-activeLineGutter': {
      backgroundColor: 'transparent',
      color: '#cba6f7',
    },
    // Gutter (line numbers)
    '.cm-gutters': {
      backgroundColor: '#181825',
      color: '#585b70',
      border: 'none',
      borderRight: '1px solid #313244',
      minWidth: '40px',
    },
    '.cm-lineNumbers .cm-gutterElement': {
      padding: '0 8px 0 4px',
      minWidth: '32px',
    },
    // Fold gutter
    '.cm-foldGutter .cm-gutterElement': {
      color: '#585b70',
    },
    '.cm-foldGutter .cm-gutterElement:hover': {
      color: '#cdd6f4',
    },
    // Bracket matching
    '.cm-matchingBracket': {
      backgroundColor: '#45475a',
      color: '#f9e2af !important',
      outline: '1px solid #585b70',
    },
    '.cm-nonmatchingBracket': {
      color: '#f38ba8 !important',
    },
    // Autocomplete dropdown
    '.cm-tooltip': {
      backgroundColor: '#1e1e2e',
      border: '1px solid #313244',
      borderRadius: '8px',
      boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
    },
    '.cm-tooltip.cm-tooltip-autocomplete': {
      maxHeight: '260px',
    },
    '.cm-tooltip.cm-tooltip-autocomplete > ul': {
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
      fontSize: '12px',
    },
    '.cm-tooltip.cm-tooltip-autocomplete > ul > li': {
      padding: '4px 12px',
      lineHeight: '1.5',
      color: '#cdd6f4',
    },
    '.cm-tooltip.cm-tooltip-autocomplete > ul > li[aria-selected]': {
      backgroundColor: '#1f77b4',
      color: '#fff',
      borderRadius: '4px',
    },
    '.cm-completionIcon': {
      opacity: '0.7',
      marginRight: '4px',
    },
    // Search panel
    '.cm-panels': {
      backgroundColor: '#181825',
      color: '#cdd6f4',
      borderTop: '1px solid #313244',
    },
    '.cm-panels input, .cm-panels button': {
      color: '#cdd6f4',
    },
    // Placeholder
    '.cm-placeholder': {
      color: '#585b70',
      fontStyle: 'italic',
    },
    // Selection match highlights
    '.cm-selectionMatch': {
      backgroundColor: '#45475a80',
      borderRadius: '2px',
    },
    // Scrollbar
    '.cm-scroller::-webkit-scrollbar': {
      width: '8px',
      height: '8px',
    },
    '.cm-scroller::-webkit-scrollbar-track': {
      backgroundColor: 'transparent',
    },
    '.cm-scroller::-webkit-scrollbar-thumb': {
      backgroundColor: '#45475a',
      borderRadius: '4px',
    },
    '.cm-scroller::-webkit-scrollbar-thumb:hover': {
      backgroundColor: '#585b70',
    },
  },
  { dark: true }
);

// ── Syntax highlighting (Catppuccin Mocha–inspired) ──
const opalHighlightStyle = HighlightStyle.define([
  // Keywords (SELECT, FROM, WHERE, etc.)
  { tag: tags.keyword, color: '#cba6f7', fontWeight: '600' },
  // Operators (=, <, >, AND, OR, NOT)
  { tag: tags.operator, color: '#89dceb' },
  { tag: tags.operatorKeyword, color: '#cba6f7' },
  // Strings
  { tag: tags.string, color: '#a6e3a1' },
  // Numbers
  { tag: tags.number, color: '#fab387' },
  // Comments
  { tag: tags.comment, color: '#6c7086', fontStyle: 'italic' },
  { tag: tags.lineComment, color: '#6c7086', fontStyle: 'italic' },
  { tag: tags.blockComment, color: '#6c7086', fontStyle: 'italic' },
  // Types (INT, VARCHAR, etc.)
  { tag: tags.typeName, color: '#f9e2af' },
  { tag: tags.standard(tags.typeName), color: '#f9e2af' },
  // Functions (COUNT, SUM, etc.)
  { tag: tags.function(tags.variableName), color: '#89b4fa' },
  // Table/column names
  { tag: tags.name, color: '#cdd6f4' },
  // Identifiers / properties
  { tag: tags.propertyName, color: '#94e2d5' },
  // Punctuation
  { tag: tags.punctuation, color: '#9399b2' },
  { tag: tags.paren, color: '#9399b2' },
  { tag: tags.squareBracket, color: '#9399b2' },
  // Special
  { tag: tags.null, color: '#f38ba8', fontStyle: 'italic' },
  { tag: tags.bool, color: '#fab387' },
  // Catch-all
  { tag: tags.definition(tags.variableName), color: '#89b4fa' },
]);

export default function SqlEditor({
  value,
  onChange,
  onExecute,
  schema,
  schemaName,
  height = '200px',
  placeholder = 'SELECT * FROM person LIMIT 10',
}: SqlEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const sqlCompartment = useRef(new Compartment());
  const onChangeRef = useRef(onChange);
  const onExecuteRef = useRef(onExecute);
  onChangeRef.current = onChange;
  onExecuteRef.current = onExecute;

  const buildSqlConfig = useCallback((): SQLConfig => {
    const config: SQLConfig = {
      dialect: PostgreSQL,
      upperCaseKeywords: true,
    };
    if (schema) {
      const completionSchema: Record<string, string[]> = {};
      for (const [table, columns] of Object.entries(schema)) {
        completionSchema[table] = columns;
        if (schemaName) {
          completionSchema[`${schemaName}.${table}`] = columns;
        }
      }
      config.schema = completionSchema;
      if (schemaName) {
        config.defaultSchema = schemaName;
      }
    }
    return config;
  }, [schema, schemaName]);

  useEffect(() => {
    if (!containerRef.current) return;

    const heightTheme = EditorView.theme({
      '&': { height },
    });

    const executeKeymap = keymap.of([
      {
        key: 'Ctrl-Enter',
        mac: 'Cmd-Enter',
        run: () => {
          onExecuteRef.current?.();
          return true;
        },
      },
    ]);

    const updateListener = EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        onChangeRef.current(update.state.doc.toString());
      }
    });

    const state = EditorState.create({
      doc: value,
      extensions: [
        // Core
        lineNumbers(),
        highlightActiveLineGutter(),
        history(),
        foldGutter(),
        drawSelection(),
        dropCursor(),
        indentOnInput(),
        bracketMatching(),
        closeBrackets(),
        rectangularSelection(),
        crosshairCursor(),
        highlightActiveLine(),
        highlightSelectionMatches(),
        // Keymaps
        executeKeymap,
        keymap.of([
          indentWithTab,
          ...closeBracketsKeymap,
          ...defaultKeymap,
          ...searchKeymap,
          ...historyKeymap,
          ...foldKeymap,
          ...completionKeymap,
        ]),
        // SQL
        sqlCompartment.current.of(sql(buildSqlConfig())),
        autocompletion({
          activateOnTyping: true,
          maxRenderedOptions: 30,
        }),
        // Theme
        opalDarkTheme,
        heightTheme,
        syntaxHighlighting(opalHighlightStyle),
        cmPlaceholder(placeholder),
        updateListener,
      ],
    });

    const view = new EditorView({ state, parent: containerRef.current });
    viewRef.current = view;
    return () => { view.destroy(); viewRef.current = null; };
  }, []);

  // Update schema completions
  useEffect(() => {
    if (viewRef.current) {
      viewRef.current.dispatch({
        effects: sqlCompartment.current.reconfigure(sql(buildSqlConfig())),
      });
    }
  }, [buildSqlConfig]);

  // Sync external value
  useEffect(() => {
    const view = viewRef.current;
    if (view && view.state.doc.toString() !== value) {
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: value },
      });
    }
  }, [value]);

  return <div ref={containerRef} style={{ borderRadius: 8 }} />;
}
