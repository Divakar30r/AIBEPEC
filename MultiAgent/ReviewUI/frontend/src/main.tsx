import React from 'react'
import ReactDOM from 'react-dom/client'
import { Alert, AlertTitle, Box, Button, CssBaseline, ThemeProvider, createTheme } from '@mui/material'
import App from './App'

const theme = createTheme({ palette: { mode: 'light' }, components: { MuiButton: { defaultProps: { size: 'small' } } } })

/** Shows a render error instead of a blank page (and logs it to the browser console). */
class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('ReviewUI crashed:', error, info.componentStack)
  }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">
          <AlertTitle>The page crashed</AlertTitle>
          <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{String(this.state.error.stack ?? this.state.error)}</pre>
        </Alert>
        <Button sx={{ mt: 2 }} variant="contained" onClick={() => this.setState({ error: null })}>Try again</Button>
      </Box>
    )
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </ThemeProvider>
  </React.StrictMode>,
)
