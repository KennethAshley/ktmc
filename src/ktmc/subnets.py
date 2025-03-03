import bittensor as bt
import logging
import asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Bot:
    def __init__(self, wallet, subtensor, subnets=None):
        self.wallet = wallet
        self.subtensor = subtensor
        self.subnets = subnets
        
        self.last_processed = {}
    
    async def wait_epoch(self, netuid):
        """
        Waits for the next epoch to start on a specific subnet.
        """
        q_tempo = [v for (k, v) in self.subtensor.query_map_subtensor("Tempo") if k == netuid]
        if len(q_tempo) == 0:
            raise Exception(f"could not determine tempo for subnet {netuid}")
        tempo = q_tempo[0].value
        logging.info(f"tempo for subnet {netuid} = {tempo}")

        await self.wait_interval(tempo, netuid)
        return tempo

    def next_tempo(self, current_block: int, tempo: int, netuid: int) -> int:
        """
        Calculates the next tempo block for a specific subnet.
        """
        interval = tempo + 1
        last_epoch = current_block - 1 - (current_block + netuid + 1) % interval
        next_tempo_ = last_epoch + interval
        return next_tempo_

    async def wait_interval(self, tempo, netuid):
        """
        Waits until the next tempo interval starts for a specific subnet.
        """
        reporting_interval: int = 10
        current_block = self.subtensor.get_current_block()
        next_tempo_block_start = self.next_tempo(current_block, tempo, netuid)
        last_reported = None

        while current_block < next_tempo_block_start:
            await asyncio.sleep(0.25)
            current_block = self.subtensor.get_current_block()

            if last_reported is None or current_block - last_reported >= reporting_interval:
                last_reported = current_block
                print(
                    f"Current Block: {current_block}  Next tempo for netuid {netuid} at: {next_tempo_block_start}"
                )
                logging.info(
                    f"Current Block: {current_block}  Next tempo for netuid {netuid} at: {next_tempo_block_start}"
                )
        
        return next_tempo_block_start

    async def get_next_subnet_epochs(self):
        """
        Calculate the next epoch block for each subnet
        and return sorted by proximity to current block
        """
        subnet_data = []
        current_block = self.subtensor.get_current_block()
        
        for subnet in self.subnets:
            netuid = subnet['netuid']
            stake_amount = subnet['stake_amount']
            
            try:
                # Get tempo
                q_tempo = [v for (k, v) in self.subtensor.query_map_subtensor("Tempo") if k == netuid]
                if len(q_tempo) == 0:
                    logger.warning(f"Could not determine tempo for subnet {netuid}")
                    continue
                    
                tempo = q_tempo[0].value
                
                # Calculate next epoch
                next_epoch = self.next_tempo(current_block, tempo, netuid)
                blocks_to_epoch = next_epoch - current_block
                
                subnet_data.append({
                    'netuid': netuid,
                    'stake_amount': stake_amount,
                    'next_epoch': next_epoch,
                    'blocks_to_epoch': blocks_to_epoch,
                    'tempo': tempo
                })
                
                logger.info(f"Subnet {netuid}: Next epoch at block {next_epoch} ({blocks_to_epoch} blocks away)")
                
            except Exception as e:
                logger.error(f"Error getting epoch data for subnet {netuid}: {e}")
        
        # Sort by epoch
        subnet_data.sort(key=lambda x: x['blocks_to_epoch'])
        return subnet_data

    async def execute_subnet_strategy(self, subnet_info):
        """
        Execute strategy for a single subnet
        """
        netuid = subnet_info['netuid']
        stake_amount = subnet_info['stake_amount']
        tempo = subnet_info['tempo']
        next_epoch_block = subnet_info['next_epoch']
        
        try:
            # LeStakeBefore
            stake_at_block = next_epoch_block - 3
            
            current_block = self.subtensor.get_current_block()
            
            # LeSkip
            if current_block > stake_at_block:
                logger.info(f"Already past staking point for subnet {netuid}")
                return False
            
            # LeWait
            while current_block < stake_at_block:
                await asyncio.sleep(0.25)
                current_block = self.subtensor.get_current_block()
            
            # LeConvert
            stake_amount_rao = int(stake_amount * 10**9)
            
            logger.info(f"Staking {stake_amount} TAO to subnet {netuid} at block {current_block}")
            
            # LeStake
            self.subtensor.add_stake(
                wallet=self.wallet,
                hotkey=self.wallet.get_hotkey(),
                amount=stake_amount_rao
            )
            
            logger.info(f"Successfully staked to subnet {netuid}")
            
            unstake_at_block = next_epoch_block + 1
            
            current_block = self.subtensor.get_current_block()
            while current_block < unstake_at_block:
                await asyncio.sleep(0.25)
                current_block = self.subtensor.get_current_block()
            
            logger.info(f"Unstaking from subnet {netuid} at block {current_block}")
            
            # LeUnstake
            self.subtensor.unstake(
                wallet=self.wallet,
                hotkey=self.wallet.get_hotkey(),
                amount=stake_amount_rao
            )
            
            logger.info(f"Successfully unstaked from subnet {netuid}")
            
            self.last_processed[netuid] = current_block
            
            return True
            
        except Exception as e:
            logger.error(f"Error executing strategy for subnet {netuid}: {e}")
            return False

    async def execute_strategy(self):
        """
        Get the next subnet epochs and execute strategy for the closest ones
        """
        try:
            # Get subnet epoch
            subnet_epochs = await self.get_next_subnet_epochs()
            
            # next up
            upcoming_subnets = [
                subnet for subnet in subnet_epochs 
                if 2 <= subnet['blocks_to_epoch'] <= 10
            ]
            
            if not upcoming_subnets:
                logger.info("No subnets approaching epoch within window")
                await asyncio.sleep(10)
                return
            
            closest_subnet = upcoming_subnets[0]
            netuid = closest_subnet['netuid']
            
            # Check if we recently processed this subnet
            if netuid in self.last_processed:
                last_block = self.last_processed[netuid]
                current_block = self.subtensor.get_current_block()
                if current_block - last_block < 100:  # Don't process same subnet twice in 100 blocks
                    logger.info(f"Recently processed subnet {netuid}, skipping")
                    return
            
            logger.info(f"Executing strategy for subnet {netuid}, {closest_subnet['blocks_to_epoch']} blocks to epoch")
            await self.execute_subnet_strategy(closest_subnet)
            
        except Exception as e:
            logger.error(f"Error in execute_strategy: {e}")

async def run_continuously():
    wallet = bt.wallet(name='default')
    subtensor = bt.subtensor(network="finney")
    
    # subnets to target
    subnets = [
        {'netuid': 8, 'stake_amount': 0.5},
        {'netuid': 19, 'stake_amount': 1.0},
        {'netuid': 25, 'stake_amount': 0.75}
    ]
    
    bot = Bot(wallet, subtensor, subnets)

    # LeRun
    while True:
        try:
            await bot.execute_strategy()

            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Error in Bot loop: {e}")
            await asyncio.sleep(60)

def main():
    try:
        asyncio.run(run_continuously())

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logging.error(f"Error in main: {e}")
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()