import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
export default tseslint.config(
  {ignores:['dist','node_modules']},
  {files:['**/*.{ts,tsx}'],extends:[js.configs.recommended,...tseslint.configs.recommended],languageOptions:{globals:{...globals.browser,...globals.node}},plugins:{'react-hooks':reactHooks,'react-refresh':reactRefresh},rules:{'no-unused-vars':'off','@typescript-eslint/no-unused-vars':'warn','@typescript-eslint/no-explicit-any':'off','react-hooks/rules-of-hooks':'error','react-hooks/exhaustive-deps':'warn','react-refresh/only-export-components':'warn'}}
);
