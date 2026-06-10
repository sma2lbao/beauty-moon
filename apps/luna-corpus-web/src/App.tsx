import { Routes, Route } from 'react-router-dom'
import { Layout } from '@/components/layout/Layout'
import { QAPage } from '@/pages/QAPage'
import { DocumentsPage } from '@/pages/DocumentsPage'
import { StatusPage } from '@/pages/StatusPage'
import { SettingsPage } from '@/pages/SettingsPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<QAPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="status" element={<StatusPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}

export default App
