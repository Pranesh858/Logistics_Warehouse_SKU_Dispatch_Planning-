import { useEffect, useRef, useState, FormEvent } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Eye,
  EyeOff,
  Loader2,
  Mail,
  Phone,
  PackageSearch,
  ShieldCheck,
  ArrowRight,
  ArrowLeft,
  CheckCircle2,
} from "lucide-react";

/**
 * LoginPage — DispatchIQ
 *
 * React + TypeScript, Tailwind. Requires `framer-motion` for the
 * transitions (npm install framer-motion).
 *
 * Supports:
 *  - Sign in / Create account, toggled via pill tabs and a bottom link
 *  - Email + password, or phone + OTP, as the login/signup method
 *  - Mock auth throughout — swap the mock* functions for real API calls
 */

export type UserRole = "Planner" | "Warehouse Team" | "Manager" | "Admin";
export type AuthMode = "signin" | "signup";
export type AuthMethod = "email" | "phone";

export interface AuthenticatedUser {
  name: string;
  email?: string;
  phone?: string;
  role: UserRole;
}

interface LoginPageProps {
  onLoginSuccess: (user: AuthenticatedUser) => void;
  appName?: string;
}

const ROLES: UserRole[] = ["Planner", "Warehouse Team", "Manager", "Admin"];
const COUNTRY_CODES = ["+91", "+1", "+44", "+61", "+971"];
const DEMO_OTP = "123456";

interface FormState {
  name: string;
  email: string;
  password: string;
  confirmPassword: string;
  countryCode: string;
  phone: string;
  otp: string;
  role: UserRole;
  remember: boolean;
  agreeTerms: boolean;
}

const initialForm: FormState = {
  name: "",
  email: "",
  password: "",
  confirmPassword: "",
  countryCode: "+91",
  phone: "",
  otp: "",
  role: "Planner",
  remember: true,
  agreeTerms: false,
};

type Errors = Partial<Record<keyof FormState, string>>;

function validateEmailStep(form: FormState, mode: AuthMode): Errors {
  const errors: Errors = {};

  if (mode === "signup" && !form.name.trim()) {
    errors.name = "Name is required.";
  }
  if (!form.email.trim()) {
    errors.email = "Email is required.";
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
    errors.email = "Enter a valid email address.";
  }
  if (!form.password) {
    errors.password = "Password is required.";
  } else if (form.password.length < 6) {
    errors.password = "Password must be at least 6 characters.";
  }
  if (mode === "signup") {
    if (!form.confirmPassword) {
      errors.confirmPassword = "Confirm your password.";
    } else if (form.confirmPassword !== form.password) {
      errors.confirmPassword = "Passwords don't match.";
    }
    if (!form.agreeTerms) {
      errors.agreeTerms = "You need to accept the terms to continue.";
    }
  }
  return errors;
}

function validatePhoneStep(form: FormState, mode: AuthMode): Errors {
  const errors: Errors = {};
  if (mode === "signup" && !form.name.trim()) {
    errors.name = "Name is required.";
  }
  if (!/^\d{7,12}$/.test(form.phone.trim())) {
    errors.phone = "Enter a valid phone number.";
  }
  return errors;
}

// ---- Mock auth calls. Replace with real API requests. ----
async function mockPasswordAuth(form: FormState, mode: AuthMode): Promise<AuthenticatedUser> {
  await new Promise((r) => setTimeout(r, 900));
  if (form.password === "wrong") throw new Error("Incorrect email or password.");
  return {
    name: mode === "signup" ? form.name : form.email.split("@")[0].replace(/[._]/g, " "),
    email: form.email,
    role: form.role,
  };
}
async function mockSendOtp(): Promise<void> {
  await new Promise((r) => setTimeout(r, 700));
}
async function mockVerifyOtp(form: FormState, mode: AuthMode): Promise<AuthenticatedUser> {
  await new Promise((r) => setTimeout(r, 700));
  if (form.otp !== DEMO_OTP) throw new Error("That code didn't match. Try again.");
  return {
    name: mode === "signup" && form.name ? form.name : "Warehouse user",
    phone: `${form.countryCode} ${form.phone}`,
    role: form.role,
  };
}

// ---- Small shared UI bits ----

const inputClass = (hasError?: boolean) =>
  `w-full rounded-xl border-2 bg-white px-3.5 py-2.5 text-sm text-slate-900 placeholder:text-slate-400
   transition-colors duration-200 outline-none
   ${hasError ? "border-red-400 focus:border-red-500" : "border-slate-200 hover:border-slate-300 focus:border-[#2E5597]"}
   focus:ring-4 ${hasError ? "focus:ring-red-100" : "focus:ring-[#2E5597]/15"}`;

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="mt-1 text-xs text-red-600">{message}</p>;
}

function PillTabs<T extends string>({
  value,
  options,
  onChange,
  layoutId,
}: {
  value: T;
  options: { value: T; label: string; icon?: React.ReactNode }[];
  onChange: (v: T) => void;
  layoutId: string;
}) {
  return (
    <div className="relative grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1 border-2 border-slate-200">
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={`relative z-10 flex items-center justify-center gap-1.5 rounded-lg py-2 text-sm font-medium
              transition-colors duration-200 ${active ? "text-white" : "text-slate-500 hover:text-slate-700"}`}
          >
            {active && (
              <motion.span
                layoutId={layoutId}
                transition={{ type: "spring", stiffness: 400, damping: 32 }}
                className="absolute inset-0 -z-10 rounded-lg bg-[#1F3864]"
              />
            )}
            {opt.icon}
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

const fade = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
  transition: { duration: 0.22, ease: "easeOut" as const },
};

export default function LoginPage({ onLoginSuccess, appName = "DispatchIQ" }: LoginPageProps) {
  const [mode, setMode] = useState<AuthMode>("signin");
  const [method, setMethod] = useState<AuthMethod>("email");
  const [phonePhase, setPhonePhase] = useState<"enter" | "otp">("enter");

  const [form, setForm] = useState<FormState>(initialForm);
  const [errors, setErrors] = useState<Errors>({});
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [resendCooldown, setResendCooldown] = useState(0);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (resendCooldown <= 0) {
      if (timerRef.current) clearInterval(timerRef.current);
      return;
    }
    timerRef.current = setInterval(() => setResendCooldown((s) => s - 1), 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [resendCooldown]);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (errors[key]) setErrors((prev) => ({ ...prev, [key]: undefined }));
  }

  function switchMode(next: AuthMode) {
    setMode(next);
    setErrors({});
    setFormError(null);
    setPhonePhase("enter");
    setForm((prev) => ({ ...prev, otp: "" }));
  }

  function switchMethod(next: AuthMethod) {
    setMethod(next);
    setErrors({});
    setFormError(null);
    setPhonePhase("enter");
  }

  async function handleEmailSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    const validationErrors = validateEmailStep(form, mode);
    setErrors(validationErrors);
    if (Object.keys(validationErrors).length > 0) return;

    setSubmitting(true);
    try {
      const user = await mockPasswordAuth(form, mode);
      onLoginSuccess(user);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Something went wrong. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSendOtp(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    const validationErrors = validatePhoneStep(form, mode);
    setErrors(validationErrors);
    if (Object.keys(validationErrors).length > 0) return;

    setSubmitting(true);
    try {
      await mockSendOtp();
      setPhonePhase("otp");
      setResendCooldown(30);
    } catch {
      setFormError("Couldn't send the code. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerifyOtp(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!/^\d{6}$/.test(form.otp)) {
      setErrors({ otp: "Enter the 6-digit code." });
      return;
    }
    setSubmitting(true);
    try {
      const user = await mockVerifyOtp(form, mode);
      onLoginSuccess(user);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Verification failed.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    if (resendCooldown > 0) return;
    setSubmitting(true);
    try {
      await mockSendOtp();
      setResendCooldown(30);
    } finally {
      setSubmitting(false);
    }
  }

  const stateKey = `${mode}-${method}-${phonePhase}`;

  return (
    <div className="min-h-screen w-full flex bg-[#EAF0FA]">
      {/* Left panel — brand / context, unchanged background */}
      <div className="hidden lg:flex lg:w-1/2 flex-col justify-between bg-[#1F3864] text-white p-12 relative overflow-hidden">
        <div className="absolute -right-24 -top-24 h-80 w-80 rounded-full bg-[#2E5597] opacity-40" />
        <div className="absolute -left-16 bottom-0 h-64 w-64 rounded-full bg-[#2E5597] opacity-20" />

        <div className="relative z-10 flex items-center gap-2">
          <PackageSearch className="h-7 w-7" />
          <span className="text-lg font-semibold tracking-tight">{appName}</span>
        </div>

        <div className="relative z-10 max-w-sm">
          <h1 className="text-3xl font-semibold leading-snug mb-4">
            Demand-driven dispatch planning, without the spreadsheets.
          </h1>
          <p className="text-sm text-white/75 leading-relaxed">
            Forecast SKU demand, get a recommended dispatch plan, resolve exceptions,
            and approve with full traceability, before anything reaches the WMS.
          </p>
          <div className="mt-8 flex items-center gap-2 text-xs text-white/60">
            <ShieldCheck className="h-4 w-4" />
            Role-based access. Every approval and override is logged.
          </div>
        </div>

        <div className="relative z-10 text-xs text-white/50">
          © {new Date().getFullYear()} {appName}. Internal use only.
        </div>
      </div>

      {/* Right panel — auth card */}
      <div className="flex flex-1 items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-sm">
          <div className="lg:hidden flex items-center gap-2 mb-6 text-[#1F3864]">
            <PackageSearch className="h-6 w-6" />
            <span className="text-lg font-semibold tracking-tight">{appName}</span>
          </div>

          {/* Real, elevated card */}
          <div className="rounded-2xl border-2 border-slate-200 bg-white shadow-xl shadow-slate-900/5 p-7 sm:p-8">
            {/* Sign in / Create account pills */}
            <PillTabs
              layoutId="mode-pill"
              value={mode}
              onChange={(v) => switchMode(v)}
              options={[
                { value: "signin", label: "Sign in" },
                { value: "signup", label: "Create account" },
              ]}
            />

            <div className="mt-6">
              <AnimatePresence mode="wait">
                <motion.div key={mode + "-heading"} {...fade}>
                  <h2 className="text-xl font-semibold text-[#1F3864]">
                    {mode === "signin" ? "Welcome back" : "Create your account"}
                  </h2>
                  <p className="mt-1 text-sm text-slate-500">
                    {mode === "signin"
                      ? "Sign in to open the planning dashboard."
                      : "Set up access to the planning dashboard."}
                  </p>
                </motion.div>
              </AnimatePresence>
            </div>

            {/* Email / Phone method pills */}
            <div className="mt-5">
              <PillTabs
                layoutId="method-pill"
                value={method}
                onChange={(v) => switchMethod(v)}
                options={[
                  { value: "email", label: "Email", icon: <Mail className="h-3.5 w-3.5" /> },
                  { value: "phone", label: "Phone", icon: <Phone className="h-3.5 w-3.5" /> },
                ]}
              />
            </div>

            <div className="mt-6 overflow-hidden">
              <AnimatePresence mode="wait">
                {formError && (
                  <motion.div
                    key="form-error"
                    {...fade}
                    role="alert"
                    className="mb-4 rounded-xl border-2 border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
                  >
                    {formError}
                  </motion.div>
                )}
              </AnimatePresence>

              <AnimatePresence mode="wait">
                {method === "email" && (
                  <motion.form key={stateKey} {...fade} onSubmit={handleEmailSubmit} noValidate className="space-y-4">
                    {mode === "signup" && (
                      <div>
                        <label htmlFor="name" className="block text-sm font-medium text-slate-700 mb-1.5">
                          Full name
                        </label>
                        <input
                          id="name"
                          value={form.name}
                          onChange={(e) => update("name", e.target.value)}
                          placeholder="Asha Rao"
                          className={inputClass(Boolean(errors.name))}
                        />
                        <FieldError message={errors.name} />
                      </div>
                    )}

                    <div>
                      <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-1.5">
                        Work email
                      </label>
                      <input
                        id="email"
                        type="email"
                        autoComplete="email"
                        value={form.email}
                        onChange={(e) => update("email", e.target.value)}
                        placeholder="planner@warehouse.com"
                        className={inputClass(Boolean(errors.email))}
                      />
                      <FieldError message={errors.email} />
                    </div>

                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <label htmlFor="password" className="block text-sm font-medium text-slate-700">
                          Password
                        </label>
                        {mode === "signin" && (
                          <button
                            type="button"
                            className="text-xs font-medium text-[#2E5597] hover:underline"
                            onClick={() => alert("Hook this up to your password-reset flow.")}
                          >
                            Forgot password?
                          </button>
                        )}
                      </div>
                      <div className="relative">
                        <input
                          id="password"
                          type={showPassword ? "text" : "password"}
                          autoComplete={mode === "signin" ? "current-password" : "new-password"}
                          value={form.password}
                          onChange={(e) => update("password", e.target.value)}
                          placeholder="••••••••"
                          className={inputClass(Boolean(errors.password)) + " pr-10"}
                        />
                        <button
                          type="button"
                          onClick={() => setShowPassword((v) => !v)}
                          className="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-600"
                          aria-label={showPassword ? "Hide password" : "Show password"}
                        >
                          {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                      <FieldError message={errors.password} />
                    </div>

                    {mode === "signup" && (
                      <div>
                        <label htmlFor="confirmPassword" className="block text-sm font-medium text-slate-700 mb-1.5">
                          Confirm password
                        </label>
                        <div className="relative">
                          <input
                            id="confirmPassword"
                            type={showConfirm ? "text" : "password"}
                            value={form.confirmPassword}
                            onChange={(e) => update("confirmPassword", e.target.value)}
                            placeholder="••••••••"
                            className={inputClass(Boolean(errors.confirmPassword)) + " pr-10"}
                          />
                          <button
                            type="button"
                            onClick={() => setShowConfirm((v) => !v)}
                            className="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-600"
                            aria-label={showConfirm ? "Hide password" : "Show password"}
                          >
                            {showConfirm ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                          </button>
                        </div>
                        <FieldError message={errors.confirmPassword} />
                      </div>
                    )}

                    <div>
                      <label htmlFor="role" className="block text-sm font-medium text-slate-700 mb-1.5">
                        {mode === "signin" ? "Sign in as" : "Role"}
                      </label>
                      <select
                        id="role"
                        value={form.role}
                        onChange={(e) => update("role", e.target.value as UserRole)}
                        className={inputClass() + " bg-white"}
                      >
                        {ROLES.map((role) => (
                          <option key={role} value={role}>
                            {role}
                          </option>
                        ))}
                      </select>
                    </div>

                    {mode === "signin" ? (
                      <label className="flex items-center gap-2 text-sm text-slate-600 select-none">
                        <input
                          type="checkbox"
                          checked={form.remember}
                          onChange={(e) => update("remember", e.target.checked)}
                          className="h-4 w-4 rounded border-2 border-slate-300 text-[#2E5597] focus:ring-[#2E5597]"
                        />
                        Keep me signed in on this device
                      </label>
                    ) : (
                      <div>
                        <label className="flex items-start gap-2 text-sm text-slate-600 select-none">
                          <input
                            type="checkbox"
                            checked={form.agreeTerms}
                            onChange={(e) => update("agreeTerms", e.target.checked)}
                            className="mt-0.5 h-4 w-4 rounded border-2 border-slate-300 text-[#2E5597] focus:ring-[#2E5597]"
                          />
                          I agree to the internal usage and data-handling policy.
                        </label>
                        <FieldError message={errors.agreeTerms} />
                      </div>
                    )}

                    <SubmitButton submitting={submitting} label={mode === "signin" ? "Sign in" : "Create account"} />
                  </motion.form>
                )}

                {method === "phone" && phonePhase === "enter" && (
                  <motion.form key={stateKey} {...fade} onSubmit={handleSendOtp} noValidate className="space-y-4">
                    {mode === "signup" && (
                      <div>
                        <label htmlFor="phoneName" className="block text-sm font-medium text-slate-700 mb-1.5">
                          Full name
                        </label>
                        <input
                          id="phoneName"
                          value={form.name}
                          onChange={(e) => update("name", e.target.value)}
                          placeholder="Asha Rao"
                          className={inputClass(Boolean(errors.name))}
                        />
                        <FieldError message={errors.name} />
                      </div>
                    )}

                    <div>
                      <label htmlFor="phone" className="block text-sm font-medium text-slate-700 mb-1.5">
                        Mobile number
                      </label>
                      <div className="flex gap-2">
                        <select
                          value={form.countryCode}
                          onChange={(e) => update("countryCode", e.target.value)}
                          className={inputClass() + " w-24 bg-white shrink-0"}
                        >
                          {COUNTRY_CODES.map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                        <input
                          id="phone"
                          type="tel"
                          inputMode="numeric"
                          value={form.phone}
                          onChange={(e) => update("phone", e.target.value.replace(/\D/g, ""))}
                          placeholder="98765 43210"
                          className={inputClass(Boolean(errors.phone))}
                        />
                      </div>
                      <FieldError message={errors.phone} />
                    </div>

                    <div>
                      <label htmlFor="phoneRole" className="block text-sm font-medium text-slate-700 mb-1.5">
                        {mode === "signin" ? "Sign in as" : "Role"}
                      </label>
                      <select
                        id="phoneRole"
                        value={form.role}
                        onChange={(e) => update("role", e.target.value as UserRole)}
                        className={inputClass() + " bg-white"}
                      >
                        {ROLES.map((role) => (
                          <option key={role} value={role}>
                            {role}
                          </option>
                        ))}
                      </select>
                    </div>

                    <SubmitButton submitting={submitting} label="Send OTP" icon={<ArrowRight className="h-4 w-4" />} />
                  </motion.form>
                )}

                {method === "phone" && phonePhase === "otp" && (
                  <motion.form key={stateKey} {...fade} onSubmit={handleVerifyOtp} noValidate className="space-y-4">
                    <button
                      type="button"
                      onClick={() => setPhonePhase("enter")}
                      className="flex items-center gap-1 text-xs font-medium text-[#2E5597] hover:underline"
                    >
                      <ArrowLeft className="h-3.5 w-3.5" />
                      Change number
                    </button>

                    <div className="rounded-xl border-2 border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm text-slate-600">
                      Code sent to{" "}
                      <span className="font-medium text-slate-900">
                        {form.countryCode} {form.phone}
                      </span>
                    </div>

                    <div>
                      <label htmlFor="otp" className="block text-sm font-medium text-slate-700 mb-1.5">
                        6-digit code
                      </label>
                      <input
                        id="otp"
                        inputMode="numeric"
                        maxLength={6}
                        value={form.otp}
                        onChange={(e) => update("otp", e.target.value.replace(/\D/g, ""))}
                        placeholder="123456"
                        className={inputClass(Boolean(errors.otp)) + " tracking-[0.4em] text-center text-lg"}
                      />
                      <FieldError message={errors.otp} />
                      <p className="mt-1 text-xs text-slate-400">Demo code: {DEMO_OTP}</p>
                    </div>

                    <button
                      type="button"
                      onClick={handleResend}
                      disabled={resendCooldown > 0 || submitting}
                      className="text-xs font-medium text-[#2E5597] hover:underline disabled:text-slate-400 disabled:no-underline"
                    >
                      {resendCooldown > 0 ? `Resend code in ${resendCooldown}s` : "Resend code"}
                    </button>

                    <SubmitButton submitting={submitting} label="Verify & continue" icon={<CheckCircle2 className="h-4 w-4" />} />
                  </motion.form>
                )}
              </AnimatePresence>
            </div>
          </div>

          {/* Bottom switcher link, mirrors the pill toggle */}
          <p className="mt-6 text-center text-sm text-slate-500">
            {mode === "signin" ? (
              <>
                New to {appName}?{" "}
                <button
                  type="button"
                  onClick={() => switchMode("signup")}
                  className="font-medium text-[#2E5597] hover:underline"
                >
                  Create an account
                </button>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <button
                  type="button"
                  onClick={() => switchMode("signin")}
                  className="font-medium text-[#2E5597] hover:underline"
                >
                  Sign in
                </button>
              </>
            )}
          </p>

          <p className="mt-3 text-center text-xs text-slate-400">
            Trouble signing in? Contact your warehouse system administrator.
          </p>
        </div>
      </div>
    </div>
  );
}

function SubmitButton({
  submitting,
  label,
  icon,
}: {
  submitting: boolean;
  label: string;
  icon?: React.ReactNode;
}) {
  return (
    <button
      type="submit"
      disabled={submitting}
      className="w-full flex items-center justify-center gap-2 rounded-xl bg-[#1F3864] px-4 py-2.5
        text-sm font-medium text-white transition-all duration-200 hover:bg-[#2E5597] hover:shadow-md
        active:scale-[0.99] disabled:opacity-60 disabled:cursor-not-allowed disabled:active:scale-100"
    >
      {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {submitting ? "Please wait…" : label}
    </button>
  );
}
