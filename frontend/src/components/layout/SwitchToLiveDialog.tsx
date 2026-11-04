import { useState, useEffect } from 'react'
import { ShieldAlert, Eye, EyeOff } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

export function SwitchToLiveDialog() {
  const { isSwitchToLiveOpen, closeSwitchToLive, toggleAppMode, isTogglingMode } = useThemeStore()
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset inputs whenever dialog opens or closes
  useEffect(() => {
    if (!isSwitchToLiveOpen) {
      setPassword('')
      setShowPassword(false)
      setError(null)
    }
  }, [isSwitchToLiveOpen])

  const handleOpenChange = (open: boolean) => {
    if (!open && !isTogglingMode) {
      closeSwitchToLive()
    }
  }

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!password.trim()) {
      setError('Please enter your login password')
      return
    }

    setError(null)
    const result = await toggleAppMode(password)
    if (result.success) {
      closeSwitchToLive()
      showToast.success('Switched to Live mode')
    } else {
      setError(result.message || 'Incorrect password')
    }
  }

  return (
    <Dialog open={isSwitchToLiveOpen} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit} className="space-y-4">
          <DialogHeader>
            <div className="flex items-center gap-2 text-destructive">
              <ShieldAlert className="h-5 w-5" />
              <DialogTitle>Switch to Live Mode</DialogTitle>
            </div>
            <DialogDescription className="pt-2 text-sm text-muted-foreground">
              You are currently in <strong>Analyze Mode</strong>. Switching to{' '}
              <strong className="text-destructive">Live Mode</strong> will place real orders on your connected broker account with actual capital.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2 py-2">
            <Label htmlFor="live-mode-password">OpenAlgo Login Password</Label>
            <div className="relative">
              <Input
                id="live-mode-password"
                type={showPassword ? 'text' : 'password'}
                placeholder="Enter login password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value)
                  if (error) setError(null)
                }}
                autoFocus
                disabled={isTogglingMode}
                className={error ? 'border-destructive pr-10' : 'pr-10'}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="absolute right-0 top-0 h-full px-3 py-2 hover:bg-transparent text-muted-foreground"
                onClick={() => setShowPassword(!showPassword)}
                tabIndex={-1}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </Button>
            </div>
            {error && <p className="text-xs font-medium text-destructive">{error}</p>}
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={isTogglingMode}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="destructive"
              disabled={isTogglingMode || !password.trim()}
            >
              {isTogglingMode ? (
                <div className="flex items-center gap-2">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                  <span>Verifying...</span>
                </div>
              ) : (
                'Switch to Live Mode'
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
