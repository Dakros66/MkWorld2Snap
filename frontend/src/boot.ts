import { mount } from 'svelte';
import Shell from './Shell.svelte';
import './theme.css';

const rootElement = document.getElementById('app');
if (!rootElement) {
  throw new Error('MkWorld2Snap mount point was not found.');
}

const app = mount(Shell, {
  target: rootElement,
});

export default app;
