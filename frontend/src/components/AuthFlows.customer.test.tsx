// @vitest-environment jsdom
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,describe,expect,it,vi} from 'vitest';
import {MemoryRouter} from 'react-router-dom';
import {AuthModal} from './AuthFlows';

const registerMock=vi.hoisted(()=>vi.fn());
vi.mock('../services/api',async importOriginal=>{const actual=await importOriginal<typeof import('../services/api')>();return {...actual,register:registerMock};});
afterEach(()=>{cleanup();vi.clearAllMocks();});

describe('customer account registration',()=>{
  it('offers the customer role and requires verification rather than pretending to sign in',async()=>{
    registerMock.mockResolvedValue({message:'Email delivery is disabled; no message was sent.',email_delivery_enabled:false});
    const onAuth=vi.fn();const ui=userEvent.setup();
    render(<MemoryRouter><AuthModal onClose={()=>undefined} onAuth={onAuth}/></MemoryRouter>);
    await ui.click(screen.getByRole('button',{name:'Create account'}));
    await ui.selectOptions(screen.getByLabelText('I’m here as'),'customer');
    await ui.type(screen.getByLabelText('Full name'),'Riya Customer');
    await ui.type(screen.getByLabelText('Email address'),'riya@example.com');
    await ui.type(screen.getByLabelText('Password'),'a-safe-customer-password');
    await ui.click(screen.getByRole('button',{name:/Create your account/}));
    await waitFor(()=>expect(registerMock).toHaveBeenCalledWith(expect.objectContaining({role:'customer',email:'riya@example.com'})));
    expect((await screen.findByRole('status')).textContent).toContain('no message was sent');
    expect(onAuth).not.toHaveBeenCalled();
  });
});
