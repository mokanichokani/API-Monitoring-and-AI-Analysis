/*database.js*/
// Simple in-memory database for demonstration
const { v4: uuidv4 } = require('uuid');

// In-memory database tables
const db = {
  customers: [
    { id: '1', name: 'John Doe', email: 'john@example.com', accountNumber: '10001', balance: 5000 },
    { id: '2', name: 'Jane Smith', email: 'jane@example.com', accountNumber: '10002', balance: 7500 },
    { id: '3', name: 'Robert Johnson', email: 'robert@example.com', accountNumber: '10003', balance: 12000 }
  ],
  
  transactions: [
    { 
      id: 't1', 
      accountNumber: '10001', 
      type: 'deposit', 
      amount: 1000, 
      timestamp: new Date(Date.now() - 86400000).toISOString(),
      status: 'completed'
    },
    { 
      id: 't2', 
      accountNumber: '10002', 
      type: 'withdrawal', 
      amount: 500, 
      timestamp: new Date(Date.now() - 43200000).toISOString(),
      status: 'completed'
    },
    { 
      id: 't3', 
      accountNumber: '10001', 
      type: 'transfer', 
      amount: 750, 
      destinationAccount: '10003',
      timestamp: new Date(Date.now() - 21600000).toISOString(),
      status: 'completed'
    }
  ],
  
  sessions: [],
  
  analytics: {
    activeSessions: 0,
    totalTransactions: 3,
    depositTotal: 1000,
    withdrawalTotal: 500,
    transferTotal: 750
  }
};

// Customer operations
const customerOperations = {
  getCustomers: () => {
    return db.customers;
  },
  
  getCustomerById: (id) => {
    return db.customers.find(c => c.id === id);
  },
  
  getCustomerByAccountNumber: (accountNumber) => {
    return db.customers.find(c => c.accountNumber === accountNumber);
  },
  
  getCustomerBalance: (accountNumber) => {
    const customer = db.customers.find(c => c.accountNumber === accountNumber);
    return customer ? customer.balance : null;
  },
  
  updateCustomerBalance: (accountNumber, amount) => {
    const customer = db.customers.find(c => c.accountNumber === accountNumber);
    if (customer) {
      customer.balance += amount;
      return true;
    }
    return false;
  }
};

// Transaction operations
const transactionOperations = {
  getTransactions: () => {
    return db.transactions;
  },
  
  getTransactionById: (id) => {
    return db.transactions.find(t => t.id === id);
  },
  
  getTransactionsByAccountNumber: (accountNumber) => {
    return db.transactions.filter(t => t.accountNumber === accountNumber);
  },
  
  createTransaction: (transaction) => {
    const newTransaction = {
      id: uuidv4(),
      timestamp: new Date().toISOString(),
      status: 'pending',
      ...transaction
    };
    
    db.transactions.push(newTransaction);
    
    // Update analytics
    db.analytics.totalTransactions++;
    if (transaction.type === 'deposit') {
      db.analytics.depositTotal += transaction.amount;
    } else if (transaction.type === 'withdrawal') {
      db.analytics.withdrawalTotal += transaction.amount;
    } else if (transaction.type === 'transfer') {
      db.analytics.transferTotal += transaction.amount;
    }
    
    return newTransaction;
  },
  
  updateTransactionStatus: (id, status) => {
    const transaction = db.transactions.find(t => t.id === id);
    if (transaction) {
      transaction.status = status;
      return transaction;
    }
    return null;
  },
  
  processDeposit: (accountNumber, amount) => {
    // Create transaction record
    const transaction = transactionOperations.createTransaction({
      accountNumber,
      type: 'deposit',
      amount
    });
    
    // Update customer balance
    const success = customerOperations.updateCustomerBalance(accountNumber, amount);
    
    // Update transaction status
    if (success) {
      transactionOperations.updateTransactionStatus(transaction.id, 'completed');
      return { success: true, transaction };
    }
    
    transactionOperations.updateTransactionStatus(transaction.id, 'failed');
    return { success: false, transaction };
  },
  
  processWithdrawal: (accountNumber, amount) => {
    // Check if customer has sufficient balance
    const balance = customerOperations.getCustomerBalance(accountNumber);
    if (balance === null || balance < amount) {
      const transaction = transactionOperations.createTransaction({
        accountNumber,
        type: 'withdrawal',
        amount,
        status: 'failed',
        reason: 'Insufficient funds'
      });
      return { success: false, transaction, reason: 'Insufficient funds' };
    }
    
    // Create transaction record
    const transaction = transactionOperations.createTransaction({
      accountNumber,
      type: 'withdrawal',
      amount
    });
    
    // Update customer balance
    const success = customerOperations.updateCustomerBalance(accountNumber, -amount);
    
    // Update transaction status
    if (success) {
      transactionOperations.updateTransactionStatus(transaction.id, 'completed');
      return { success: true, transaction };
    }
    
    transactionOperations.updateTransactionStatus(transaction.id, 'failed');
    return { success: false, transaction };
  },
  
  processTransfer: (sourceAccount, destinationAccount, amount) => {
    // Check if source customer has sufficient balance
    const sourceBalance = customerOperations.getCustomerBalance(sourceAccount);
    if (sourceBalance === null || sourceBalance < amount) {
      const transaction = transactionOperations.createTransaction({
        accountNumber: sourceAccount,
        destinationAccount,
        type: 'transfer',
        amount,
        status: 'failed',
        reason: 'Insufficient funds'
      });
      return { success: false, transaction, reason: 'Insufficient funds' };
    }
    
    // Check if destination account exists
    const destinationCustomer = customerOperations.getCustomerByAccountNumber(destinationAccount);
    if (!destinationCustomer) {
      const transaction = transactionOperations.createTransaction({
        accountNumber: sourceAccount,
        destinationAccount,
        type: 'transfer',
        amount,
        status: 'failed',
        reason: 'Destination account not found'
      });
      return { success: false, transaction, reason: 'Destination account not found' };
    }
    
    // Create transaction record
    const transaction = transactionOperations.createTransaction({
      accountNumber: sourceAccount,
      destinationAccount,
      type: 'transfer',
      amount
    });
    
    // Update balances
    const sourceUpdate = customerOperations.updateCustomerBalance(sourceAccount, -amount);
    const destUpdate = customerOperations.updateCustomerBalance(destinationAccount, amount);
    
    // Update transaction status
    if (sourceUpdate && destUpdate) {
      transactionOperations.updateTransactionStatus(transaction.id, 'completed');
      return { success: true, transaction };
    }
    
    // Rollback if something went wrong
    if (sourceUpdate) {
      customerOperations.updateCustomerBalance(sourceAccount, amount);
    }
    
    transactionOperations.updateTransactionStatus(transaction.id, 'failed');
    return { success: false, transaction };
  }
};

// Analytics operations
const analyticsOperations = {
  getAnalytics: () => {
    return db.analytics;
  },
  
  getTransactionSummary: () => {
    return {
      totalCount: db.transactions.length,
      completedCount: db.transactions.filter(t => t.status === 'completed').length,
      pendingCount: db.transactions.filter(t => t.status === 'pending').length,
      failedCount: db.transactions.filter(t => t.status === 'failed').length,
      depositTotal: db.analytics.depositTotal,
      withdrawalTotal: db.analytics.withdrawalTotal,
      transferTotal: db.analytics.transferTotal
    };
  },
  
  getTransactionsByType: () => {
    return {
      deposits: db.transactions.filter(t => t.type === 'deposit'),
      withdrawals: db.transactions.filter(t => t.type === 'withdrawal'),
      transfers: db.transactions.filter(t => t.type === 'transfer')
    };
  },
  
  trackSession: (sessionId, active = true) => {
    if (active) {
      db.sessions.push(sessionId);
      db.analytics.activeSessions = db.sessions.length;
    } else {
      const index = db.sessions.indexOf(sessionId);
      if (index !== -1) {
        db.sessions.splice(index, 1);
      }
      db.analytics.activeSessions = db.sessions.length;
    }
    return db.analytics.activeSessions;
  }
};

module.exports = {
  customerOperations,
  transactionOperations,
  analyticsOperations
}; 