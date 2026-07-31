import {
  AlertTriangle,
  BadgeCheck,
  ChevronDown,
  ChevronUp,
  Clock,
  Crown,
  History,
  Loader2,
  Mail,
  Monitor,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Shield,
  Trash2,
  User,
  UserPlus,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'
import { fetchCSRFToken } from '@/api/client'

interface UserRecord {
  id: number
  user_code: string | null
  username: string
  email: string
  is_admin: boolean
  totp_enabled: boolean
  status: 'ACTIVE' | 'SUSPENDED' | 'PENDING_VERIFICATION'
  email_verified: boolean
  created_at: string | null
  last_login_at: string | null
  has_active_subscription: boolean
}

interface SessionRecord {
  session_id: string
  device_info: string | null
  ip_address: string | null
  broker: string | null
  login_time: string | null
  last_seen: string | null
}

interface LoginAttemptRecord {
  ip_address: string | null
  device_info: string | null
  status: string
  login_type: string | null
  failure_reason: string | null
  timestamp: string | null
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function statusBadgeClass(status: UserRecord['status']): string {
  switch (status) {
    case 'SUSPENDED':
      return 'bg-loss/10 border-loss/20 text-loss'
    case 'PENDING_VERIFICATION':
      return 'bg-warning/10 border-warning/20 text-warning'
    default:
      return 'bg-profit/10 border-profit/20 text-profit'
  }
}

export default function UserManagement() {
  const [users, setUsers] = useState<UserRecord[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Create form state
  const [showForm, setShowForm] = useState(false)
  const [formUsername, setFormUsername] = useState('')
  const [formEmail, setFormEmail] = useState('')
  const [formPassword, setFormPassword] = useState('')
  const [formIsAdmin, setFormIsAdmin] = useState(false)
  const [isCreating, setIsCreating] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [suspendingId, setSuspendingId] = useState<number | null>(null)

  // Expanded detail drawer (sessions + login history) for one user at a time
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [sessions, setSessions] = useState<SessionRecord[]>([])
  const [loginHistory, setLoginHistory] = useState<LoginAttemptRecord[]>([])
  const [isLoadingDetail, setIsLoadingDetail] = useState(false)

  const fetchUsers = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)
      const res = await fetch('/admin/api/users', { credentials: 'include' })
      const data = await res.json()
      if (data.status === 'success') {
        setUsers(data.data)
      } else {
        setError(data.message || 'Failed to fetch users')
      }
    } catch {
      setError('Failed to connect to server')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchUsers()
  }, [fetchUsers])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formUsername.trim() || !formEmail.trim() || !formPassword.trim()) {
      showToast.error('All fields are required')
      return
    }
    setIsCreating(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const res = await fetch('/admin/api/users', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          username: formUsername.trim(),
          email: formEmail.trim(),
          password: formPassword.trim(),
          is_admin: formIsAdmin,
        }),
      })
      const data = await res.json()
      if (data.status === 'success') {
        showToast.success(data.message)
        setFormUsername('')
        setFormEmail('')
        setFormPassword('')
        setFormIsAdmin(false)
        setShowForm(false)
        await fetchUsers()
      } else {
        showToast.error(data.message || 'Failed to create user')
      }
    } catch {
      showToast.error('Network error. Please try again.')
    } finally {
      setIsCreating(false)
    }
  }

  const handleDelete = async (userId: number, username: string) => {
    if (!confirm(`Are you sure you want to delete user "${username}"? This cannot be undone.`)) return
    setDeletingId(userId)
    try {
      const csrfToken = await fetchCSRFToken()
      const res = await fetch(`/admin/api/users/${userId}`, {
        method: 'DELETE',
        credentials: 'include',
        headers: {
          'X-CSRFToken': csrfToken,
        },
      })
      const data = await res.json()
      if (data.status === 'success') {
        showToast.success(data.message)
        await fetchUsers()
      } else {
        showToast.error(data.message || 'Failed to delete user')
      }
    } catch {
      showToast.error('Network error. Please try again.')
    } finally {
      setDeletingId(null)
    }
  }

  const handleToggleDetail = async (userId: number) => {
    if (expandedId === userId) {
      setExpandedId(null)
      return
    }
    setExpandedId(userId)
    setIsLoadingDetail(true)
    try {
      const [sessionsRes, historyRes] = await Promise.all([
        fetch(`/admin/api/users/${userId}/sessions`, { credentials: 'include' }),
        fetch(`/admin/api/users/${userId}/login-history?limit=20`, { credentials: 'include' }),
      ])
      const sessionsData = await sessionsRes.json()
      const historyData = await historyRes.json()
      setSessions(sessionsData.status === 'success' ? sessionsData.data : [])
      setLoginHistory(historyData.status === 'success' ? historyData.data : [])
    } catch {
      showToast.error('Failed to load user detail')
      setSessions([])
      setLoginHistory([])
    } finally {
      setIsLoadingDetail(false)
    }
  }

  const handleSuspendToggle = async (u: UserRecord) => {
    const action = u.status === 'SUSPENDED' ? 'reactivate' : 'suspend'
    setSuspendingId(u.id)
    try {
      const csrfToken = await fetchCSRFToken()
      const res = await fetch(`/admin/api/users/${u.id}/${action}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'X-CSRFToken': csrfToken },
      })
      const data = await res.json()
      if (data.status === 'success') {
        showToast.success(data.message)
        await fetchUsers()
      } else {
        showToast.error(data.message || `Failed to ${action} user`)
      }
    } catch {
      showToast.error('Network error. Please try again.')
    } finally {
      setSuspendingId(null)
    }
  }

  return (
    <div className="space-y-8 max-w-5xl mx-auto pb-10">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-xs font-semibold text-brand uppercase tracking-wider block mb-1">
            Admin Panel
          </span>
          <h1 className="text-xl font-bold text-foreground tracking-tight">User Management</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Create, view and manage platform accounts</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={fetchUsers}
            className="p-2 rounded-lg bg-card border border-border hover:border-muted-foreground/40 text-muted-foreground hover:text-foreground transition-all"
            title="Refresh"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setShowForm((v) => !v)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand hover:bg-brand/90 text-brand-foreground font-bold text-sm transition-colors shadow-md shadow-brand/10"
          >
            {showForm ? <X className="h-4 w-4" /> : <UserPlus className="h-4 w-4" />}
            {showForm ? 'Cancel' : 'Add User'}
          </button>
        </div>
      </div>

      {/* Create User Form */}
      {showForm && (
        <div className="p-6 rounded-2xl bg-card border border-brand/20">
          <h2 className="text-lg font-bold text-foreground mb-5 flex items-center gap-2">
            <UserPlus className="h-5 w-5 text-brand" />
            Create New User
          </h2>
          <form onSubmit={handleCreate} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="new-username" className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                Username
              </Label>
              <Input
                id="new-username"
                placeholder="e.g. john_doe"
                value={formUsername}
                onChange={(e) => setFormUsername(e.target.value)}
                className="bg-background border-border focus:border-brand/40 text-foreground"
                autoComplete="off"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="new-email" className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                Email
              </Label>
              <Input
                id="new-email"
                type="email"
                placeholder="john@example.com"
                value={formEmail}
                onChange={(e) => setFormEmail(e.target.value)}
                className="bg-background border-border focus:border-brand/40 text-foreground"
                autoComplete="off"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="new-password" className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                Password
              </Label>
              <Input
                id="new-password"
                type="password"
                placeholder="Min. 8 characters"
                value={formPassword}
                onChange={(e) => setFormPassword(e.target.value)}
                className="bg-background border-border focus:border-brand/40 text-foreground"
                autoComplete="new-password"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                Role
              </Label>
              <div className="flex items-center gap-3 h-10">
                <button
                  type="button"
                  onClick={() => setFormIsAdmin((v) => !v)}
                  className={cn(
                    'flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-bold transition-all',
                    formIsAdmin
                      ? 'bg-brand/10 border-brand/30 text-brand'
                      : 'bg-background border-border text-muted-foreground hover:border-muted-foreground/40'
                  )}
                >
                  {formIsAdmin ? <Crown className="h-3.5 w-3.5" /> : <User className="h-3.5 w-3.5" />}
                  {formIsAdmin ? 'Admin' : 'Regular User'}
                </button>
                <span className="text-[10px] text-muted-foreground">
                  {formIsAdmin ? 'Full access + user management' : 'Standard trading access only'}
                </span>
              </div>
            </div>

            <div className="sm:col-span-2 flex justify-end">
              <Button
                type="submit"
                disabled={isCreating}
                className="bg-brand hover:bg-brand/90 text-brand-foreground font-bold px-6"
              >
                {isCreating ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Creating…
                  </>
                ) : (
                  <>
                    <Plus className="h-4 w-4 mr-2" />
                    Create Account
                  </>
                )}
              </Button>
            </div>
          </form>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="p-4 rounded-xl bg-loss/10 border border-loss/20 flex items-center gap-3">
          <AlertTriangle className="h-5 w-5 text-loss shrink-0" />
          <p className="text-sm text-loss">{error}</p>
        </div>
      )}

      {/* Users Table */}
      <div className="rounded-2xl bg-card border border-border overflow-hidden">
        <div className="p-5 border-b border-border flex items-center justify-between">
          <h2 className="text-base font-bold text-foreground flex items-center gap-2">
            <Shield className="h-4 w-4 text-brand" />
            Platform Accounts
            <span className="ml-1 text-xs font-semibold text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
              {users.length}
            </span>
          </h2>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-16 gap-3 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm font-medium">Loading users…</span>
          </div>
        ) : users.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
            <User className="h-8 w-8" />
            <p className="text-sm font-medium">No users found</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {users.map((u) => (
              <div key={u.id}>
                <div className="flex items-center justify-between px-5 py-4 hover:bg-muted/40 transition-colors group">
                  <div className="flex items-center gap-4 min-w-0">
                    {/* Avatar */}
                    <div
                      className={cn(
                        'w-9 h-9 rounded-full flex items-center justify-center text-sm font-extrabold shrink-0',
                        u.is_admin
                          ? 'bg-brand/15 text-brand border border-brand/20'
                          : 'bg-muted text-muted-foreground border border-border'
                      )}
                    >
                      {u.username.charAt(0).toUpperCase()}
                    </div>

                    {/* Info */}
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-bold text-foreground">{u.username}</span>
                        {u.user_code && (
                          <span className="text-[10px] font-mono text-muted-foreground">
                            {u.user_code}
                          </span>
                        )}
                        {u.is_admin && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider rounded bg-brand/10 border border-brand/20 text-brand">
                            <Crown className="h-2.5 w-2.5" />
                            Admin
                          </span>
                        )}
                        {u.totp_enabled && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider rounded bg-profit/10 border border-profit/20 text-profit">
                            <Shield className="h-2.5 w-2.5" />
                            2FA
                          </span>
                        )}
                        <span
                          className={cn(
                            'inline-flex items-center gap-1 px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider rounded border',
                            statusBadgeClass(u.status)
                          )}
                        >
                          {u.status.replace('_', ' ')}
                        </span>
                        {u.has_active_subscription && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider rounded bg-brand/10 border border-brand/20 text-brand">
                            <BadgeCheck className="h-2.5 w-2.5" />
                            Subscribed
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 mt-0.5 text-[11px] text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <Mail className="h-3 w-3" />
                          <span className="truncate">{u.email}</span>
                        </span>
                        <span className="flex items-center gap-1 shrink-0">
                          <Clock className="h-3 w-3" />
                          Last login: {formatDate(u.last_login_at)}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 shrink-0 ml-4">
                    <button
                      type="button"
                      onClick={() => handleToggleDetail(u.id)}
                      className="p-2 rounded-lg bg-card border border-border text-muted-foreground hover:text-foreground hover:border-muted-foreground/40 transition-all"
                      title="Sessions & login history"
                    >
                      {expandedId === u.id ? (
                        <ChevronUp className="h-3.5 w-3.5" />
                      ) : (
                        <ChevronDown className="h-3.5 w-3.5" />
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleSuspendToggle(u)}
                      disabled={suspendingId === u.id || u.is_admin}
                      className={cn(
                        'p-2 rounded-lg border transition-all disabled:opacity-40',
                        u.status === 'SUSPENDED'
                          ? 'bg-profit/10 border-profit/10 text-profit hover:bg-profit/20 hover:border-profit/30'
                          : 'bg-warning/10 border-warning/10 text-warning hover:bg-warning/20 hover:border-warning/30'
                      )}
                      title={
                        u.is_admin
                          ? 'Admins cannot be suspended'
                          : u.status === 'SUSPENDED'
                            ? `Reactivate ${u.username}`
                            : `Suspend ${u.username}`
                      }
                    >
                      {suspendingId === u.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : u.status === 'SUSPENDED' ? (
                        <Play className="h-3.5 w-3.5" />
                      ) : (
                        <Pause className="h-3.5 w-3.5" />
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(u.id, u.username)}
                      disabled={deletingId === u.id}
                      className="p-2 rounded-lg bg-loss/10 border border-loss/10 text-loss hover:bg-loss/20 hover:border-loss/30 transition-all disabled:opacity-50"
                      title={`Delete ${u.username}`}
                    >
                      {deletingId === u.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="h-3.5 w-3.5" />
                      )}
                    </button>
                  </div>
                </div>

                {/* Expanded detail: sessions + login history */}
                {expandedId === u.id && (
                  <div className="px-5 pb-5 bg-muted/20">
                    {isLoadingDetail ? (
                      <div className="flex items-center gap-2 text-xs text-muted-foreground py-4">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Loading detail…
                      </div>
                    ) : (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                        <div>
                          <h3 className="text-[11px] font-black uppercase tracking-wider text-muted-foreground flex items-center gap-1.5 mb-2">
                            <Monitor className="h-3 w-3" />
                            Active Sessions ({sessions.length})
                          </h3>
                          {sessions.length === 0 ? (
                            <p className="text-xs text-muted-foreground">No active sessions</p>
                          ) : (
                            <div className="space-y-1.5">
                              {sessions.map((s) => (
                                <div
                                  key={s.session_id}
                                  className="text-[11px] rounded-lg bg-card border border-border px-3 py-2"
                                >
                                  <div className="text-foreground font-medium truncate">
                                    {s.device_info || 'Unknown device'}
                                  </div>
                                  <div className="text-muted-foreground">
                                    {s.ip_address || '—'} · {formatDate(s.last_seen)}
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>

                        <div>
                          <h3 className="text-[11px] font-black uppercase tracking-wider text-muted-foreground flex items-center gap-1.5 mb-2">
                            <History className="h-3 w-3" />
                            Recent Login Attempts
                          </h3>
                          {loginHistory.length === 0 ? (
                            <p className="text-xs text-muted-foreground">No login history</p>
                          ) : (
                            <div className="space-y-1.5 max-h-60 overflow-y-auto">
                              {loginHistory.map((h, idx) => (
                                <div
                                  key={idx}
                                  className="text-[11px] rounded-lg bg-card border border-border px-3 py-2 flex items-center justify-between gap-2"
                                >
                                  <div className="min-w-0">
                                    <div className="text-muted-foreground truncate">
                                      {h.ip_address || '—'} · {formatDate(h.timestamp)}
                                    </div>
                                    {h.failure_reason && (
                                      <div className="text-loss truncate">{h.failure_reason}</div>
                                    )}
                                  </div>
                                  <span
                                    className={cn(
                                      'shrink-0 px-1.5 py-0.5 rounded text-[9px] font-black uppercase',
                                      h.status === 'success'
                                        ? 'bg-profit/10 text-profit'
                                        : 'bg-loss/10 text-loss'
                                    )}
                                  >
                                    {h.status}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Security notice */}
      <div className="p-4 rounded-xl bg-card border border-border flex items-start gap-3">
        <Shield className="h-4 w-4 text-brand shrink-0 mt-0.5" />
        <div className="text-xs text-muted-foreground space-y-1">
          <p className="font-semibold text-muted-foreground">Security Notes</p>
          <p>• Each user gets isolated broker credentials and session data.</p>
          <p>• Passwords are hashed with Argon2 and are never stored in plain text.</p>
          <p>• Users can enable 2FA (TOTP) from their own Profile settings.</p>
          <p>• Share the login URL and credentials with users directly — no registration email is sent automatically.</p>
        </div>
      </div>

    </div>
  )
}
