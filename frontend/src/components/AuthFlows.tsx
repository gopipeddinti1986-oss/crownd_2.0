import {FormEvent,useEffect,useState} from 'react';
import {Link,useLocation} from 'react-router-dom';
import {ArrowRight,Check,X} from 'lucide-react';
import {authErrorMessage,confirmPasswordReset,confirmVerification,login,register,requestPasswordReset,requestVerification,User} from '../services/api';

type AuthMode='login'|'register'|'forgot'|'verify';
export function AuthModal({onClose,onAuth}:{onClose:()=>void;onAuth:(user:User)=>void}){
  const [mode,setMode]=useState<AuthMode>('login');
  const [role,setRole]=useState<'creator'|'brand'|'customer'>('creator');
  const [name,setName]=useState('');
  const [email,setEmail]=useState('');
  const [password,setPassword]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [emailDeliveryEnabled,setEmailDeliveryEnabled]=useState<boolean|null>(null);
  async function submit(event:FormEvent){
    event.preventDefault();setBusy(true);setError('');setNotice('');
    try{
      if(mode==='login'){
        const user=await login(email,password);onAuth(user);return;
      }
      if(mode==='register'){
        const result=await register({name,email,password,role,brand_name:name,username:name.toLowerCase().replace(/\s+/g,'_')});
        setEmailDeliveryEnabled(result.email_delivery_enabled);setNotice(result.message);setMode('verify');return;
      }
      const result=mode==='forgot'?await requestPasswordReset(email):await requestVerification(email);
      setEmailDeliveryEnabled(result.email_delivery_enabled);setNotice(result.message);
    }catch(err){setError(authErrorMessage(err,'Unable to complete this request. Please try again.'));}
    finally{setBusy(false);}
  }
  const title=mode==='login'?'Good to have you back.':mode==='register'?'Find your people.':mode==='forgot'?'Reset your password.':'Check your email.';
  return <div className="modal-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget)onClose();}}><section className="auth-modal" aria-modal="true" role="dialog" aria-labelledby="auth-title">
    <button className="modal-close" onClick={onClose} aria-label="Close sign in"><X size={18}/></button>
    <Link to="/" className="brand-lockup dark"><span className="crownd-mark">C</span><span>CROWND<small>CREATOR COMMERCE</small></span></Link>
    <div className="eyebrow">{mode==='login'?'WELCOME BACK':mode==='register'?'MAKE IT COUNT':'ACCOUNT ACCESS'}</div>
    <h2 id="auth-title">{title}</h2>
    <p>{mode==='login'?'Sign in to your CROWND workspace.':mode==='register'?'Create your account. We’ll ask you to verify your email before sign-in.':mode==='forgot'?'Request a one-time password reset link.':'Request a fresh verification link for your account.'}</p>
    {(mode==='login'||mode==='register')&&<div className="auth-tabs"><button className={mode==='login'?'selected':''} onClick={()=>{setMode('login');setNotice('');setError('');}}>Log in</button><button className={mode==='register'?'selected':''} onClick={()=>{setMode('register');setNotice('');setError('');}}>Create account</button></div>}
    {notice&&<div className="auth-notice" role="status"><span>{emailDeliveryEnabled?<Check size={15}/>:<span aria-hidden="true">!</span>}</span><p>{notice}</p></div>}
    <form onSubmit={submit}>
      {mode==='register'&&<><label>Full name<input required minLength={2} maxLength={120} value={name} onChange={event=>setName(event.target.value)} placeholder="Your name" autoComplete="name"/></label><label>I’m here as<select value={role} onChange={event=>setRole(event.target.value as 'creator'|'brand'|'customer')}><option value="creator">A creator</option><option value="brand">A brand</option><option value="customer">A customer</option></select></label></>}
      <label>Email address<input required type="email" maxLength={254} value={email} onChange={event=>setEmail(event.target.value)} placeholder="you@example.com" autoComplete="email"/></label>
      {mode==='login'||mode==='register'?<label>Password<input required minLength={mode==='register'?12:1} maxLength={128} type="password" value={password} onChange={event=>setPassword(event.target.value)} placeholder={mode==='register'?'At least 12 characters':'Your password'} autoComplete={mode==='register'?'new-password':'current-password'}/></label>:null}
      {error&&<div className="form-error" role="alert">{error}</div>}
      <button className="btn dark-btn auth-submit" disabled={busy}>{busy?'Please wait…':mode==='login'?'Log in to CROWND':mode==='register'?'Create your account':mode==='forgot'?'Send reset instructions':'Request verification link'} <ArrowRight size={15}/></button>
    </form>
    {(mode==='login'||mode==='forgot'||mode==='verify')&&<div className="auth-secondary">{mode==='login'?<><button onClick={()=>{setMode('forgot');setNotice('');setError('');}}>Forgot password?</button><button onClick={()=>{setMode('verify');setNotice('');setError('');}}>Resend verification email</button></>:<button onClick={()=>{setMode('login');setNotice('');setError('');}}>Back to log in</button>}</div>}
    <small className="auth-terms">By continuing, you agree to CROWND’s terms and privacy policy.</small>
  </section></div>;
}

export function EmailActionPage({kind}:{kind:'verify'|'reset'}){
  const location=useLocation();
  const token=new URLSearchParams(location.hash.slice(1)).get('token')||'';
  const [state,setState]=useState<'loading'|'ready'|'complete'|'error'>(kind==='verify'?'loading':'ready');
  const [message,setMessage]=useState(kind==='verify'?'Verifying your email link…':'Choose a new password for your account.');
  const [password,setPassword]=useState('');
  const [busy,setBusy]=useState(false);
  useEffect(()=>{
    if(kind!=='verify')return;
    if(!token){setState('error');setMessage('This verification link is missing or invalid. Request a new link from sign in.');return;}
    let active=true;
    confirmVerification(token).then(result=>{if(active){setState('complete');setMessage(result.message);window.history.replaceState(null,'',location.pathname);}}).catch(()=>{if(active){setState('error');setMessage('This verification link is invalid, expired, or already used. Request a fresh link from sign in.');}});
    return()=>{active=false;};
  },[kind,token,location.pathname]);
  async function submit(event:FormEvent){event.preventDefault();if(!token){setState('error');setMessage('This reset link is missing. Request a new one from sign in.');return;}setBusy(true);setMessage('');try{const result=await confirmPasswordReset(token,password);setState('complete');setMessage(result.message);window.history.replaceState(null,'',location.pathname);}catch{setState('error');setMessage('This reset link is invalid, expired, or already used. Request a fresh link from sign in.');}finally{setBusy(false);}}
  return <main className="email-action-page"><section className="email-action-card"><Link to="/" className="brand-lockup dark"><span className="crownd-mark">C</span><span>CROWND<small>CREATOR COMMERCE</small></span></Link><div className="eyebrow">{kind==='verify'?'EMAIL VERIFICATION':'PASSWORD RECOVERY'}</div><h1>{kind==='verify'?'Confirm your email':'Choose a new password'}</h1><p role="status">{message}</p>{kind==='reset'&&state!=='complete'&&<form onSubmit={submit}><label>New password<input type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={password} onChange={event=>setPassword(event.target.value)} placeholder="At least 12 characters"/></label><button className="btn dark-btn auth-submit" disabled={busy}>{busy?'Saving…':'Update password'} <ArrowRight size={15}/></button></form>}<Link className="outline-btn" to="/" onClick={()=>window.dispatchEvent(new Event('crownd:open-auth'))}>Back to CROWND sign in</Link></section></main>;
}
