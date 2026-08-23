import React from 'react';

export const Button = ({ htmlType, type, loading, disabled, children, ...props }) => (
  <button type={htmlType || 'button'} disabled={disabled || loading} {...props}>
    {children}
  </button>
);

export const Input = ({ prefix, ...props }) => (
  <label>
    {prefix}
    <input {...props} />
  </label>
);

Input.Password = ({ prefix, ...props }) => (
  <label>
    {prefix}
    <input {...props} type="password" />
  </label>
);

export const Checkbox = ({ children, ...props }) => (
  <label>
    <input type="checkbox" {...props} />
    {children}
  </label>
);

export const Card = ({ children, ...props }) => <section {...props}>{children}</section>;

export const Form = ({ onFinish, children, ...props }) => (
  <form
    {...props}
    onSubmit={(event) => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.currentTarget));
      if (!values.username || !values.password) return;
      onFinish?.(values);
    }}
  >
    {children}
  </form>
);

Form.useForm = () => [{}];
Form.Item = ({ name, children }) => (
  <div>
    {React.isValidElement(children) ? React.cloneElement(children, { name }) : children}
  </div>
);

const Text = ({ children, ...props }) => <span {...props}>{children}</span>;
const Title = ({ children, level = 1, ...props }) => {
  const Tag = `h${level}`;
  return <Tag {...props}>{children}</Tag>;
};

export const message = {
  success: () => {},
  error: () => {},
};

export const Typography = { Title, Text };
